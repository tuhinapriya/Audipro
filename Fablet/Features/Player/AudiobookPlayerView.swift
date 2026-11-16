import SwiftUI
import UIKit

struct AudiobookPlayerView: View {
    @Environment(AppModel.self) private var model
    @State private var isScrubbing = false
    @State private var scrubTime = 0.0

    private let speeds: [Double] = [0.75, 1, 1.25, 1.5, 1.75, 2]

    var body: some View {
        GeometryReader { geometry in
            ZStack {
                LinearGradient(
                    colors: [Color(red: 0.16, green: 0.14, blue: 0.25), Color(red: 0.06, green: 0.06, blue: 0.10)],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )
                .ignoresSafeArea()

                ScrollView {
                    VStack(spacing: 24) {
                        header
                        if let production = model.player.production {
                            artwork
                                .frame(maxWidth: min(geometry.size.width - 48, 340))
                                .frame(maxWidth: .infinity)

                            VStack(spacing: 8) {
                                Text(production.title ?? "Untitled audiobook")
                                    .font(.title2.bold())
                                    .multilineTextAlignment(.center)
                                    .frame(maxWidth: .infinity)
                                if let description = production.description, !description.isEmpty {
                                    Text(description)
                                        .font(.subheadline)
                                        .foregroundStyle(.white.opacity(0.7))
                                        .multilineTextAlignment(.center)
                                }
                            }

                            progress
                            controls
                            if let error = model.player.error {
                                Text(error)
                                    .font(.footnote)
                                    .foregroundStyle(.orange)
                                    .multilineTextAlignment(.center)
                                    .accessibilityLabel("Playback error: \(error)")
                            } else if model.player.isBuffering {
                                HStack(spacing: 8) {
                                    ProgressView().tint(.white)
                                    Text("Loading audio…")
                                }
                                .font(.footnote)
                                .foregroundStyle(.white.opacity(0.7))
                                .accessibilityElement(children: .combine)
                            }
                        } else {
                            ContentUnavailableView("No audiobook selected", systemImage: "headphones", description: Text("Choose an audiobook from your library."))
                                .foregroundStyle(.white)
                        }
                    }
                    .padding(.horizontal, 24)
                    .padding(.top, 12)
                    .padding(.bottom, 32)
                    .frame(maxWidth: 600)
                    .frame(maxWidth: .infinity)
                }
            }
            .foregroundStyle(.white)
        }
        .onChange(of: model.player.production?.id) { _, _ in
            isScrubbing = false
            scrubTime = model.player.currentTime
        }
    }

    private var header: some View {
        HStack {
            Button {
                model.player.isPresented = false
            } label: {
                Image(systemName: "chevron.down")
                    .font(.headline)
                    .frame(width: 44, height: 44)
                    .background(.white.opacity(0.1), in: Circle())
            }
            .accessibilityLabel("Close player")
            Spacer()
            Text("NOW PLAYING")
                .font(.caption.weight(.semibold))
                .tracking(2)
                .foregroundStyle(.white.opacity(0.7))
            Spacer()
            Color.clear.frame(width: 44, height: 44).accessibilityHidden(true)
        }
    }

    private var artwork: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 22)
                .fill(LinearGradient(colors: [.indigo.opacity(0.75), .purple.opacity(0.45)], startPoint: .topLeading, endPoint: .bottomTrailing))
            if let image = model.player.coverImage {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFill()
            } else {
                Image(systemName: "waveform")
                    .font(.system(size: 64, weight: .light))
                    .foregroundStyle(.white.opacity(0.8))
            }
        }
        .aspectRatio(1, contentMode: .fit)
        .clipShape(RoundedRectangle(cornerRadius: 22))
        .shadow(color: .black.opacity(0.3), radius: 20, y: 10)
        .accessibilityLabel(model.player.coverImage == nil ? "Audiobook cover placeholder" : "Audiobook cover")
    }

    private var progress: some View {
        let duration = max(0, model.player.duration)
        let value = isScrubbing ? scrubTime : model.player.currentTime
        return VStack(spacing: 4) {
            Slider(
                value: Binding(
                    get: { min(max(0, value), max(duration, 1)) },
                    set: { value in
                        scrubTime = value
                        // VoiceOver can adjust a slider without beginning a drag.
                        if !isScrubbing { model.player.seek(to: value) }
                    }
                ),
                in: 0...max(duration, 1),
                onEditingChanged: { editing in
                    if editing {
                        scrubTime = min(max(0, model.player.currentTime), max(duration, 1))
                        isScrubbing = true
                    } else {
                        model.player.seek(to: scrubTime)
                        isScrubbing = false
                    }
                }
            )
            .tint(.white)
            .disabled(duration <= 0)
            .accessibilityLabel("Playback position")
            .accessibilityValue("\(timeString(value)) of \(timeString(duration))")
            HStack {
                Text(timeString(value))
                Spacer()
                Text(timeString(duration))
            }
            .font(.caption.monospacedDigit())
            .foregroundStyle(.white.opacity(0.7))
            .accessibilityHidden(true)
        }
    }

    private var controls: some View {
        HStack(spacing: 0) {
            Menu {
                ForEach(speeds, id: \.self) { speed in
                    Button {
                        model.player.setSpeed(speed)
                    } label: {
                        if model.player.speed == speed {
                            Label(speedString(speed), systemImage: "checkmark")
                        } else {
                            Text(speedString(speed))
                        }
                    }
                }
            } label: {
                Text(speedString(model.player.speed))
                    .font(.subheadline.bold().monospacedDigit())
                    .frame(minWidth: 48, minHeight: 48)
            }
            .accessibilityLabel("Playback speed")
            .accessibilityValue(speedString(model.player.speed))

            Spacer(minLength: 8)
            Button { model.player.skip(-15) } label: {
                Image(systemName: "gobackward.15")
                    .font(.title2)
                    .frame(width: 48, height: 48)
            }
            .accessibilityLabel("Back 15 seconds")
            Spacer(minLength: 8)
            Button { model.player.togglePlayback() } label: {
                Image(systemName: model.player.isPlaying || model.player.isBuffering ? "pause.fill" : "play.fill")
                    .font(.title2)
                    .foregroundStyle(Color(red: 0.08, green: 0.07, blue: 0.12))
                    .frame(width: 72, height: 72)
                    .background(.white, in: Circle())
            }
            .accessibilityLabel(model.player.isPlaying || model.player.isBuffering ? "Pause" : "Play")
            Spacer(minLength: 8)
            Button { model.player.skip(15) } label: {
                Image(systemName: "goforward.15")
                    .font(.title2)
                    .frame(width: 48, height: 48)
            }
            .accessibilityLabel("Forward 15 seconds")
            Spacer(minLength: 8)
            // Balances the speed menu without presenting an inactive control.
            Color.clear.frame(width: 48, height: 48).accessibilityHidden(true)
        }
        .buttonStyle(.plain)
    }

    private func timeString(_ seconds: Double) -> String {
        guard seconds.isFinite, seconds >= 0 else { return "0:00" }
        let total = Int(min(seconds, Double(Int.max / 2)))
        let hours = total / 3600
        let minutes = (total % 3600) / 60
        let remainder = total % 60
        return hours > 0
            ? String(format: "%d:%02d:%02d", hours, minutes, remainder)
            : String(format: "%d:%02d", minutes, remainder)
    }

    private func speedString(_ speed: Double) -> String {
        "\(speed.formatted(.number.precision(.fractionLength(0...2))))×"
    }
}
