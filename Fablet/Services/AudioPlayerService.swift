import AVFoundation
import Foundation
import MediaPlayer
import Observation
import UIKit

/// Owns the app's single audio session and player. Keep one instance for the app lifetime.
@Observable @MainActor
final class AudioPlayerService {
    var production: Production?
    var isPresented = false
    var isPlaying = false
    var currentTime: Double = 0
    var duration: Double = 0
    var speed: Double
    var isBuffering = false
    var error: String?
    private(set) var coverImage: UIImage?

    /// Resolve this ID through the repository at launch, then call `open(_:using:)` to restore.
    static var lastProductionID: String? {
        UserDefaults.standard.string(forKey: Keys.lastID)
    }

    private enum Keys {
        static let lastID = "fablet.player.lastProductionID"
        static let position = "fablet.player.position"
        static let speed = "fablet.player.speed"
    }

    @ObservationIgnored private let player = AVPlayer()
    @ObservationIgnored private var repository: (any ProductionRepository)?
    @ObservationIgnored private var sessionID = UUID()
    @ObservationIgnored private var itemID = UUID()
    @ObservationIgnored private var wantsToPlay = false
    @ObservationIgnored private var isOpening = false
    @ObservationIgnored private var isInterrupted = false
    @ObservationIgnored private var resumeAfterInterruption = false
    @ObservationIgnored private var pendingPosition: Double?
    @ObservationIgnored private var recoveryAttempted = false
    @ObservationIgnored private var coverRecoveryAttempted = false
    @ObservationIgnored private var periodicObserver: Any?
    @ObservationIgnored private var statusObservation: NSKeyValueObservation?
    @ObservationIgnored private var durationObservation: NSKeyValueObservation?
    @ObservationIgnored private var timeControlObservation: NSKeyValueObservation?
    @ObservationIgnored private var notifications: [NSObjectProtocol] = []
    @ObservationIgnored private var itemNotifications: [NSObjectProtocol] = []
    @ObservationIgnored private var remoteTargets: [(MPRemoteCommand, Any)] = []
    @ObservationIgnored private var refreshTask: Task<Void, Never>?
    @ObservationIgnored private var refreshTimer: Task<Void, Never>?
    @ObservationIgnored private var coverTask: Task<Void, Never>?
    @ObservationIgnored private var lastPersistedSecond = -1

    init() {
        let savedSpeed = UserDefaults.standard.double(forKey: Keys.speed)
        speed = Self.validSpeed(savedSpeed) ? savedSpeed : 1
        player.automaticallyWaitsToMinimizeStalling = true
        observePlayer()
        observeAudioSession()
        installRemoteCommands()
    }

    func open(_ production: Production, using repository: any ProductionRepository) async {
        // A second tap on the same book should not restart the current stream.
        if self.production?.id == production.id, player.currentItem != nil {
            self.production = production
            self.repository = repository
            if !wantsToPlay { play() }
            updateNowPlaying()
            return
        }

        persistPosition()
        sessionID = UUID()
        let session = sessionID
        refreshTask?.cancel()
        refreshTimer?.cancel()
        coverTask?.cancel()
        refreshTask = nil
        clearItemObservers()
        player.pause()
        player.replaceCurrentItem(with: nil)
        self.production = production
        self.repository = repository
        error = nil
        coverImage = nil
        isPlaying = false
        isBuffering = true
        isOpening = true
        wantsToPlay = true
        resumeAfterInterruption = false
        recoveryAttempted = false
        coverRecoveryAttempted = false
        duration = max(0, production.durationSeconds.map { Double($0) } ?? 0)
        let defaults = UserDefaults.standard
        currentTime = defaults.string(forKey: Keys.lastID) == production.id
            ? max(0, defaults.double(forKey: Keys.position)) : 0
        pendingPosition = currentTime
        defaults.set(production.id, forKey: Keys.lastID)
        defaults.set(currentTime, forKey: Keys.position)
        lastPersistedSecond = -1
        updateNowPlaying()

        guard activateAudioSession() else {
            isOpening = false
            isBuffering = false
            wantsToPlay = false
            return
        }
        do {
            let urls = try await repository.playbackURL(id: production.id)
            guard session == sessionID else { return }
            isOpening = false
            install(urls, session: session, position: currentTime)
        } catch {
            guard session == sessionID else { return }
            isOpening = false
            isBuffering = false
            wantsToPlay = false
            self.error = "Unable to load this audiobook. Please try again."
            updateNowPlaying()
        }
    }

    func togglePlayback() {
        if wantsToPlay { pause() } else { play() }
    }

    func seek(to seconds: Double) {
        guard seconds.isFinite, production != nil else { return }
        let target = duration > 0 ? min(max(0, seconds), duration) : max(0, seconds)
        currentTime = target
        persistPosition()
        updateNowPlaying()
        if pendingPosition != nil {
            pendingPosition = target
            return
        }
        guard let item = player.currentItem, item.status == .readyToPlay else {
            pendingPosition = target
            return
        }
        pendingPosition = nil
        player.seek(to: CMTime(seconds: target, preferredTimescale: 600), toleranceBefore: .zero, toleranceAfter: .zero)
    }

    func skip(_ seconds: Double) {
        guard seconds.isFinite else { return }
        seek(to: currentTime + seconds)
    }

    func setSpeed(_ speed: Double) {
        guard Self.validSpeed(speed) else { return }
        self.speed = speed
        UserDefaults.standard.set(speed, forKey: Keys.speed)
        if wantsToPlay, !isInterrupted, player.currentItem?.status == .readyToPlay, pendingPosition == nil {
            player.rate = Float(speed)
        }
        updateNowPlaying()
    }

    /// Discard private media and signed URLs when the authenticated session ends.
    func resetSession() {
        persistPosition()
        sessionID = UUID()
        refreshTask?.cancel()
        refreshTimer?.cancel()
        coverTask?.cancel()
        refreshTask = nil
        refreshTimer = nil
        coverTask = nil
        clearItemObservers()
        player.pause()
        player.replaceCurrentItem(with: nil)
        repository = nil
        production = nil
        coverImage = nil
        pendingPosition = nil
        wantsToPlay = false
        isOpening = false
        isInterrupted = false
        resumeAfterInterruption = false
        isPlaying = false
        isBuffering = false
        isPresented = false
        currentTime = 0
        duration = 0
        error = nil
        updateNowPlaying()
    }

    private static func validSpeed(_ value: Double) -> Bool {
        value.isFinite && (0.5...3.0).contains(value)
    }

    private func play() {
        guard production != nil else { return }
        wantsToPlay = true
        resumeAfterInterruption = false
        if isInterrupted {
            resumeAfterInterruption = true
            return
        }
        guard activateAudioSession() else {
            wantsToPlay = false
            return
        }
        error = nil
        if duration > 0, currentTime >= duration - 0.25 { seek(to: 0) }
        guard let item = player.currentItem else {
            isBuffering = true
            if !isOpening { refreshAccess(afterFailure: true) }
            return
        }
        if item.status == .failed {
            isBuffering = true
            recoveryAttempted = false // An explicit retry gets one new access attempt.
            refreshAccess(afterFailure: true)
        } else if item.status == .readyToPlay, pendingPosition == nil {
            player.playImmediately(atRate: Float(speed))
        } else {
            isBuffering = true
        }
        updateNowPlaying()
    }

    private func pause() {
        wantsToPlay = false
        resumeAfterInterruption = false
        player.pause()
        isPlaying = false
        isBuffering = false
        persistPosition()
        updateNowPlaying()
    }

    @discardableResult
    private func activateAudioSession() -> Bool {
        do {
            try AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio)
            try AVAudioSession.sharedInstance().setActive(true)
            return true
        } catch {
            self.error = "Audio playback is unavailable. Please try again."
            return false
        }
    }

    private func install(_ urls: PlaybackURLs, session: UUID, position: Double) {
        guard session == sessionID else { return }
        refreshTimer?.cancel()
        clearItemObservers()
        player.pause()
        itemID = UUID()
        let currentItemID = itemID
        let item = AVPlayerItem(url: urls.audioURL)
        pendingPosition = position
        isPlaying = false
        isBuffering = wantsToPlay
        player.replaceCurrentItem(with: item)

        statusObservation = item.observe(\.status, options: [.initial, .new]) { [weak self, weak item] _, _ in
            Task { @MainActor [weak self, weak item] in
                guard let self, let item, self.sessionID == session, self.itemID == currentItemID else { return }
                self.handleStatus(item, session: session, itemID: currentItemID)
            }
        }
        durationObservation = item.observe(\.duration, options: [.initial, .new]) { [weak self, weak item] _, _ in
            Task { @MainActor [weak self, weak item] in
                guard let self, let item, self.sessionID == session, self.itemID == currentItemID else { return }
                let seconds = item.duration.seconds
                if seconds.isFinite && seconds > 0 {
                    self.duration = seconds
                    self.updateNowPlaying()
                }
            }
        }
        let center = NotificationCenter.default
        itemNotifications.append(center.addObserver(forName: .AVPlayerItemDidPlayToEndTime, object: item, queue: .main) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, self.sessionID == session, self.itemID == currentItemID else { return }
                self.wantsToPlay = false
                self.isPlaying = false
                self.isBuffering = false
                if self.duration > 0 { self.currentTime = self.duration }
                self.persistPosition()
                self.updateNowPlaying()
            }
        })
        itemNotifications.append(center.addObserver(forName: .AVPlayerItemFailedToPlayToEndTime, object: item, queue: .main) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, self.sessionID == session, self.itemID == currentItemID else { return }
                self.handleItemFailure()
            }
        })
        itemNotifications.append(center.addObserver(forName: .AVPlayerItemNewErrorLogEntry, object: item, queue: .main) { [weak self, weak item] _ in
            Task { @MainActor [weak self, weak item] in
                guard let self, let item, self.sessionID == session, self.itemID == currentItemID,
                      let code = item.errorLog()?.events.last?.errorStatusCode,
                      code == 401 || code == 403 else { return }
                self.handleItemFailure()
            }
        })
        loadCover(urls.coverURL, session: session)
        scheduleRefresh(expiresAt: urls.expiresAt, session: session)
        updateNowPlaying()
    }

    private func handleStatus(_ item: AVPlayerItem, session: UUID, itemID: UUID) {
        switch item.status {
        case .readyToPlay:
            error = nil
            let position = pendingPosition ?? currentTime
            let target = duration > 0 ? min(position, duration) : position
            // Keep the pending marker until the seek completes so periodic observation
            // cannot overwrite the restored position with the new item's initial zero.
            player.seek(to: CMTime(seconds: max(0, target), preferredTimescale: 600), toleranceBefore: .zero, toleranceAfter: .zero) { [weak self] finished in
                Task { @MainActor [weak self] in
                    guard let self, self.sessionID == session, self.itemID == itemID else { return }
                    guard finished else { return }
                    // A newer user seek wins over this restoration.
                    if self.pendingPosition == position {
                        self.pendingPosition = nil
                        self.currentTime = target
                    } else if let newer = self.pendingPosition {
                        self.pendingPosition = nil
                        self.seek(to: newer)
                    }
                    self.isBuffering = false
                    if self.wantsToPlay && !self.isInterrupted { self.player.playImmediately(atRate: Float(self.speed)) }
                    self.updateNowPlaying()
                }
            }
        case .failed:
            handleItemFailure()
        case .unknown:
            isBuffering = wantsToPlay
        @unknown default:
            break
        }
    }

    private func handleItemFailure() {
        isPlaying = false
        isBuffering = wantsToPlay
        // AVPlayer may report one failed request through both its status and error log.
        if refreshTask != nil {
            recoveryAttempted = true
            return
        }
        if !recoveryAttempted {
            recoveryAttempted = true
            refreshAccess(afterFailure: true)
        } else {
            wantsToPlay = false
            isBuffering = false
            error = "Playback failed. Tap play to try again."
            updateNowPlaying()
        }
    }

    private func scheduleRefresh(expiresAt: String, session: UUID, retryDelay: TimeInterval? = nil) {
        refreshTimer?.cancel()
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let fractional = formatter.date(from: expiresAt)
        formatter.formatOptions = [.withInternetDateTime]
        let expiry = fractional ?? formatter.date(from: expiresAt)
        // An invalid expiry is not treated as an indefinitely valid URL.
        let delay = retryDelay ?? max(5, (expiry?.timeIntervalSinceNow ?? 65) - 60)
        refreshTimer = Task { [weak self] in
            do { try await Task.sleep(for: .seconds(delay)) } catch { return }
            guard let self, self.sessionID == session, !Task.isCancelled else { return }
            self.refreshAccess(afterFailure: false)
        }
    }

    private func refreshAccess(afterFailure: Bool) {
        guard refreshTask == nil, let repository, let id = production?.id else { return }
        let session = sessionID
        refreshTask = Task { [weak self] in
            do {
                let urls = try await repository.playbackURL(id: id)
                guard let self, self.sessionID == session, !Task.isCancelled else { return }
                self.refreshTask = nil
                let position = self.pendingPosition ?? self.currentTime
                self.install(urls, session: session, position: position)
            } catch {
                guard let self, self.sessionID == session, !Task.isCancelled else { return }
                self.refreshTask = nil
                if afterFailure || self.player.currentItem?.status == .failed || self.player.currentItem == nil {
                    self.wantsToPlay = false
                    self.isPlaying = false
                    self.isBuffering = false
                    self.error = "Unable to refresh playback access. Tap play to retry."
                } else {
                    // Keep the existing stream running and retry without a tight loop.
                    self.scheduleRefresh(expiresAt: "", session: session, retryDelay: 30)
                }
                self.updateNowPlaying()
            }
        }
    }

    private func loadCover(_ url: URL, session: UUID) {
        coverTask?.cancel()
        coverTask = Task { [weak self] in
            do {
                let (data, response) = try await URLSession.shared.data(from: url)
                guard !Task.isCancelled, let response = response as? HTTPURLResponse,
                      let self, self.sessionID == session else { return }
                if response.statusCode == 401 || response.statusCode == 403 {
                    if !self.coverRecoveryAttempted {
                        self.coverRecoveryAttempted = true
                        self.refreshAccess(afterFailure: false)
                    }
                    return
                }
                guard (200...299).contains(response.statusCode), let image = UIImage(data: data) else { return }
                self.coverImage = image
                self.updateNowPlaying()
            } catch {
                // Cover art is optional; playback must not fail because of it.
            }
        }
    }

    private func observePlayer() {
        periodicObserver = player.addPeriodicTimeObserver(forInterval: CMTime(seconds: 0.5, preferredTimescale: 600), queue: .main) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, self.pendingPosition == nil, self.player.currentItem != nil else { return }
            let seconds = self.player.currentTime().seconds
                guard seconds.isFinite, seconds >= 0 else { return }
                self.currentTime = seconds
                let wholeSecond = Int(seconds)
                if wholeSecond != self.lastPersistedSecond {
                    self.lastPersistedSecond = wholeSecond
                    self.persistPosition()
                    self.updateNowPlaying()
                }
            }
        }
        timeControlObservation = player.observe(\.timeControlStatus, options: [.initial, .new]) { [weak self] _, _ in
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.isPlaying = self.player.timeControlStatus == .playing && self.wantsToPlay
                self.isBuffering = self.wantsToPlay && (self.pendingPosition != nil || self.player.timeControlStatus == .waitingToPlayAtSpecifiedRate)
                if self.isPlaying { self.recoveryAttempted = false }
                self.updateNowPlaying()
            }
        }
    }

    private func observeAudioSession() {
        let center = NotificationCenter.default
        notifications.append(center.addObserver(forName: AVAudioSession.interruptionNotification, object: nil, queue: .main) { [weak self] notification in
            let rawType = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt
            let rawOptions = notification.userInfo?[AVAudioSessionInterruptionOptionKey] as? UInt ?? 0
            Task { @MainActor [weak self] in
                guard let self, let rawType, let type = AVAudioSession.InterruptionType(rawValue: rawType) else { return }
                if type == .began {
                    self.isInterrupted = true
                    self.resumeAfterInterruption = self.wantsToPlay
                    self.player.pause()
                    self.isPlaying = false
                    self.isBuffering = false
                    self.persistPosition()
                    self.updateNowPlaying()
                } else if type == .ended {
                    self.isInterrupted = false
                    let shouldResume = AVAudioSession.InterruptionOptions(rawValue: rawOptions).contains(.shouldResume)
                    let resume = self.resumeAfterInterruption && self.wantsToPlay && shouldResume
                    self.resumeAfterInterruption = false
                    if resume { self.play() } else { self.pause() }
                }
            }
        })
        notifications.append(center.addObserver(forName: AVAudioSession.routeChangeNotification, object: nil, queue: .main) { [weak self] notification in
            let rawReason = notification.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt
            Task { @MainActor [weak self] in
                guard let self, let rawReason,
                      AVAudioSession.RouteChangeReason(rawValue: rawReason) == .oldDeviceUnavailable else { return }
                self.pause()
            }
        })
    }

    private func installRemoteCommands() {
        let center = MPRemoteCommandCenter.shared()
        func add(_ command: MPRemoteCommand, _ action: @escaping @MainActor (AudioPlayerService) -> Void) {
            command.isEnabled = true
            let token = command.addTarget { [weak self] _ in
                guard self != nil else { return .commandFailed }
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    action(self)
                }
                return .success
            }
            remoteTargets.append((command, token))
        }
        add(center.playCommand) { $0.play() }
        add(center.pauseCommand) { $0.pause() }
        add(center.togglePlayPauseCommand) { $0.togglePlayback() }
        center.skipForwardCommand.preferredIntervals = [15]
        center.skipBackwardCommand.preferredIntervals = [15]
        add(center.skipForwardCommand) { $0.skip(15) }
        add(center.skipBackwardCommand) { $0.skip(-15) }
        center.changePlaybackPositionCommand.isEnabled = true
        let token = center.changePlaybackPositionCommand.addTarget { [weak self] event in
            guard self != nil, let event = event as? MPChangePlaybackPositionCommandEvent else { return .commandFailed }
            let position = event.positionTime
            Task { @MainActor [weak self] in self?.seek(to: position) }
            return .success
        }
        remoteTargets.append((center.changePlaybackPositionCommand, token))
    }

    private func updateNowPlaying() {
        guard let production else {
            MPNowPlayingInfoCenter.default().nowPlayingInfo = nil
            return
        }
        var info: [String: Any] = [
            MPMediaItemPropertyTitle: production.title ?? "Untitled audiobook",
            MPMediaItemPropertyMediaType: MPMediaType.audioBook.rawValue,
            MPNowPlayingInfoPropertyElapsedPlaybackTime: currentTime,
            MPNowPlayingInfoPropertyPlaybackRate: isPlaying ? speed : 0,
            MPNowPlayingInfoPropertyDefaultPlaybackRate: speed
        ]
        if duration > 0 { info[MPMediaItemPropertyPlaybackDuration] = duration }
        if let image = coverImage {
            info[MPMediaItemPropertyArtwork] = MPMediaItemArtwork(boundsSize: image.size) { _ in image }
        }
        MPNowPlayingInfoCenter.default().nowPlayingInfo = info
    }

    private func persistPosition() {
        guard let production, currentTime.isFinite else { return }
        let defaults = UserDefaults.standard
        defaults.set(production.id, forKey: Keys.lastID)
        defaults.set(max(0, currentTime), forKey: Keys.position)
    }

    private func clearItemObservers() {
        statusObservation?.invalidate()
        durationObservation?.invalidate()
        statusObservation = nil
        durationObservation = nil
        for token in itemNotifications { NotificationCenter.default.removeObserver(token) }
        itemNotifications.removeAll()
    }

    deinit {
        refreshTask?.cancel()
        refreshTimer?.cancel()
        coverTask?.cancel()
        statusObservation?.invalidate()
        durationObservation?.invalidate()
        timeControlObservation?.invalidate()
        if let periodicObserver { player.removeTimeObserver(periodicObserver) }
        for token in notifications + itemNotifications { NotificationCenter.default.removeObserver(token) }
        for (command, token) in remoteTargets { command.removeTarget(token) }
    }
}
