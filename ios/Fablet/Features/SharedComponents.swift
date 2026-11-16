import Foundation
import SwiftUI
import UIKit

// Shared visual language for the feature screens. No asset or service dependencies.
enum FabletColors {
    static let background = Color(red: 11 / 255, green: 11 / 255, blue: 16 / 255)
    static let surface = Color(red: 23 / 255, green: 23 / 255, blue: 32 / 255)
    static let surfaceRaised = Color(red: 32 / 255, green: 30 / 255, blue: 43 / 255)
    static let ink = Color(red: 248 / 255, green: 247 / 255, blue: 244 / 255)
    static let muted = Color(red: 164 / 255, green: 164 / 255, blue: 176 / 255)
    static let accent = Color(red: 245 / 255, green: 184 / 255, blue: 91 / 255)
    static let violet = Color(red: 157 / 255, green: 140 / 255, blue: 255 / 255)
    static let line = Color.white.opacity(0.09)
    static let danger = Color(red: 0.94, green: 0.58, blue: 0.52)
}

struct FabletScreenBackground: View {
    var body: some View {
        FabletColors.background.ignoresSafeArea()
    }
}

struct FabletEyebrow: View {
    let text: String
    var body: some View {
        Text(text.uppercased())
            .font(.system(size: 10, weight: .bold, design: .rounded))
            .tracking(2)
            .foregroundStyle(FabletColors.accent)
    }
}

struct FabletSectionHeading: View {
    let title: String
    var subtitle: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title)
                .font(.system(.title2, design: .serif, weight: .medium))
                .foregroundStyle(FabletColors.ink)
            if let subtitle {
                Text(subtitle)
                    .font(.subheadline)
                    .foregroundStyle(FabletColors.muted)
            }
        }
    }
}

struct FabletPrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(FabletColors.background)
            .frame(maxWidth: .infinity, minHeight: 54)
            .background(FabletColors.accent.opacity(configuration.isPressed ? 0.75 : 1), in: RoundedRectangle(cornerRadius: 16))
            .scaleEffect(configuration.isPressed ? 0.99 : 1)
    }
}

struct FabletCard: ViewModifier {
    func body(content: Content) -> some View {
        content
            .background(FabletColors.surface, in: RoundedRectangle(cornerRadius: 22))
            .overlay(RoundedRectangle(cornerRadius: 22).stroke(FabletColors.line, lineWidth: 1))
    }
}

extension View {
    func fabletCard() -> some View { modifier(FabletCard()) }
}

// Fetch authorized artwork once per production and cache the decoded image in memory.
struct FabletArtwork: View {
    var large = false
    var production: Production? = nil
    @Environment(AppModel.self) private var model

    var body: some View {
        GeometryReader { proxy in
            ZStack {
                RoundedRectangle(cornerRadius: large ? 24 : 14)
                    .fill(LinearGradient(colors: [Color(red: 0.37, green: 0.31, blue: 0.33), Color(red: 0.13, green: 0.17, blue: 0.22), FabletColors.background], startPoint: .topLeading, endPoint: .bottomTrailing))
                if let production, let image = model.covers[production.id] ?? (model.player.production?.id == production.id ? model.player.coverImage : nil) {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFill()
                        .frame(width: proxy.size.width, height: proxy.size.height)
                } else {
                    Circle()
                        .stroke(FabletColors.violet.opacity(0.4), lineWidth: 1)
                        .frame(width: proxy.size.width * 0.64, height: proxy.size.width * 0.64)
                    Circle()
                        .stroke(FabletColors.accent.opacity(0.18), lineWidth: 1)
                        .frame(width: proxy.size.width * 0.48, height: proxy.size.width * 0.48)
                    Image(systemName: "waveform")
                        .font(.system(size: max(18, proxy.size.width * 0.17), weight: .ultraLight))
                        .foregroundStyle(FabletColors.accent.opacity(0.8))
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: large ? 24 : 14))
        }
        .aspectRatio(1, contentMode: .fit)
        .accessibilityHidden(true)
        .task(id: "\(production?.id ?? "")-\(production?.assetsAvailable ?? false)") {
            if let production { await model.loadCover(production) }
        }
    }
}

struct FabletStatusPill: View {
    let production: Production

    private var tint: Color {
        switch production.status {
        case .completed: return FabletColors.accent
        case .failed: return FabletColors.danger
        default: return FabletColors.violet
        }
    }

    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(tint).frame(width: 6, height: 6)
            Text(production.status.label)
                .font(.caption.weight(.semibold))
                .lineLimit(1)
        }
        .foregroundStyle(tint)
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .background(tint.opacity(0.11), in: Capsule())
        .accessibilityElement(children: .combine)
    }
}

struct FabletProgressBar: View {
    let percent: Double
    private var safePercent: Double { percent.isFinite ? min(max(percent, 0), 100) : 0 }

    var body: some View {
        GeometryReader { geometry in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.white.opacity(0.08))
                Capsule().fill(FabletColors.accent)
                    .frame(width: geometry.size.width * safePercent / 100)
            }
        }
        .frame(height: 5)
        .accessibilityLabel("Production progress")
        .accessibilityValue(percent.isFinite ? "\(Int(safePercent.rounded())) percent" : "Unavailable")
    }
}

struct FabletProductionRow: View {
    let production: Production

    var body: some View {
        HStack(alignment: .center, spacing: 15) {
            FabletArtwork(production: production).frame(width: 78)
            VStack(alignment: .leading, spacing: 7) {
                Text(fabletProductionTitle(production))
                    .font(.system(.headline, design: .serif, weight: .medium))
                    .foregroundStyle(FabletColors.ink)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
                Text(production.status == .completed ? fabletDuration(production) : fabletStageMessage(production))
                    .font(.caption)
                    .foregroundStyle(FabletColors.muted)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
                FabletStatusPill(production: production)
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right")
                .font(.caption.weight(.semibold))
                .foregroundStyle(FabletColors.muted)
        }
        .padding(14)
        .fabletCard()
        .contentShape(Rectangle())
    }
}

struct FabletDemoBadge: View {
    let mode: String
    var body: some View {
        if mode.localizedCaseInsensitiveContains("demo") || mode.localizedCaseInsensitiveContains("mock") {
            HStack(spacing: 6) {
                Image(systemName: "sparkles")
                Text("Demo mode")
            }
            .font(.caption2.weight(.semibold))
            .foregroundStyle(FabletColors.accent)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(FabletColors.accent.opacity(0.1), in: Capsule())
            .accessibilityLabel("Demo mode")
        }
    }
}

struct FabletErrorBanner: View {
    let message: String
    var body: some View {
        Label(message, systemImage: "exclamationmark.circle")
            .font(.subheadline)
            .foregroundStyle(FabletColors.danger)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16)
            .background(FabletColors.danger.opacity(0.1), in: RoundedRectangle(cornerRadius: 16))
    }
}

func fabletProductionTitle(_ production: Production) -> String {
    let title = production.title?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    if !title.isEmpty { return title }
    let prompt = production.prompt.trimmingCharacters(in: .whitespacesAndNewlines)
    return prompt.isEmpty ? "Untitled production" : prompt
}

func fabletStageMessage(_ production: Production) -> String {
    let message = production.stageMessage.trimmingCharacters(in: .whitespacesAndNewlines)
    return message.isEmpty ? production.status.stageDescription : message
}

func fabletDuration(_ production: Production) -> String {
    let seconds = production.durationSeconds ?? production.durationMinutesRequested * 60
    guard seconds.isFinite, seconds > 0, seconds < Double(Int.max) else { return "—" }
    let total = Int(seconds.rounded())
    return total < 60 ? "\(total) sec" : "\(total / 60):\(String(format: "%02d", total % 60))"
}
