import Combine
import AVFoundation
import Foundation

/// A separate local store, deliberately without a worker or simulated progression.
@MainActor
final class DemoProductionRepository: ProductionRepository {
    static let sampleID = "local-sample:macos-narration"
    static let sampleDescription = "Pre-rendered locally with macOS narration; not a Convex production."

    private let subject: CurrentValueSubject<[Production], Error>
    private let fileURL: URL
    private let sampleURLs: PlaybackURLs?
    private let sample: Production?
    private var queuedRecords: [Production]
    private var loadError: Error?

    nonisolated static func bundledResource(_ name: String, extension fileExtension: String) -> URL? {
        Bundle.main.url(forResource: name, withExtension: fileExtension)
            ?? Bundle.main.url(forResource: name, withExtension: fileExtension, subdirectory: "Resources/Demo")
            ?? Bundle.main.url(forResource: name, withExtension: fileExtension, subdirectory: "Demo")
    }

    init(fileURL: URL? = nil,
         sampleAudioURL: URL? = DemoProductionRepository.bundledResource("local-sample", extension: "mp3"),
         sampleCoverURL: URL? = DemoProductionRepository.bundledResource("local-sample", extension: "png")) {
        let directory = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Fablet", isDirectory: true)
        self.fileURL = fileURL ?? directory.appendingPathComponent("demo-productions.json")
        var records: [Production] = []
        if FileManager.default.fileExists(atPath: self.fileURL.path) {
            do {
                records = try JSONDecoder().decode([Production].self, from: Data(contentsOf: self.fileURL))
                guard records.allSatisfy({ $0.status == .queued && $0.progressPercent == 0 && !$0.assetsAvailable }) else {
                    throw DemoStoreError.unavailable
                }
            }
            catch { loadError = error }
        }
        queuedRecords = records
        if let audioURL = sampleAudioURL, let coverURL = sampleCoverURL,
           audioURL.isFileURL, coverURL.isFileURL,
           FileManager.default.isReadableFile(atPath: coverURL.path),
           let player = try? AVAudioPlayer(contentsOf: audioURL),
           player.duration.isFinite, player.duration > 0,
           !records.contains(where: { $0.id == Self.sampleID }) {
            sampleURLs = PlaybackURLs(audioURL: audioURL, coverURL: coverURL, expiresAt: "")
            sample = Production(id: Self.sampleID, status: .completed, progressPercent: 100,
                stageMessage: Self.sampleDescription, createdAt: "2026-01-01T00:00:00Z",
                updatedAt: "2026-01-01T00:00:00Z", prompt: Self.sampleDescription,
                durationMinutesRequested: 0, style: .calmExplainer, title: "Locally narrated sample",
                description: Self.sampleDescription, durationSeconds: player.duration,
                assetsAvailable: true, errorMessage: nil)
        } else {
            sampleURLs = nil
            sample = nil
        }
        subject = CurrentValueSubject((sample.map { [$0] } ?? []) + records)
    }

    func list() -> AnyPublisher<[Production], Error> {
        if loadError != nil { return Fail(error: DemoStoreError.unavailable).eraseToAnyPublisher() }
        return subject.eraseToAnyPublisher()
    }

    func get(id: String) -> AnyPublisher<Production?, Error> {
        if loadError != nil { return Fail(error: DemoStoreError.unavailable).eraseToAnyPublisher() }
        return subject.map { $0.first { $0.id == id } }.eraseToAnyPublisher()
    }

    func create(prompt: String, duration: Int, style: AudiobookStyle) async throws -> String {
        guard loadError == nil else { throw DemoStoreError.unavailable }
        let prompt = try validateProductionInput(prompt: prompt, duration: duration)
        let now = ISO8601DateFormatter().string(from: Date())
        let production = Production(id: UUID().uuidString, status: .queued, progressPercent: 0,
            stageMessage: "Demo only — saved locally; no production worker is running.",
            createdAt: now, updatedAt: now, prompt: prompt, durationMinutesRequested: duration,
            style: style, title: nil, description: nil, durationSeconds: nil,
            assetsAvailable: false, errorMessage: nil)
        let records = [production] + queuedRecords
        do {
            try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try JSONEncoder().encode(records).write(to: fileURL, options: [.atomic, .completeFileProtectionUnlessOpen])
        } catch { throw DemoStoreError.unavailable }
        queuedRecords = records
        subject.send((sample.map { [$0] } ?? []) + records)
        return production.id
    }

    func playbackURL(id: String) async throws -> PlaybackURLs {
        guard loadError == nil, id == Self.sampleID, let urls = sampleURLs,
              FileManager.default.isReadableFile(atPath: urls.coverURL.path),
              let player = try? AVAudioPlayer(contentsOf: urls.audioURL),
              player.duration.isFinite, player.duration > 0 else {
            throw RepositoryError.playbackUnavailable
        }
        return urls
    }

    private enum DemoStoreError: LocalizedError {
        case unavailable
        var errorDescription: String? { "The local demo library could not be read or saved." }
    }
}