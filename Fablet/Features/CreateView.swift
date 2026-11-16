import Foundation
import SwiftUI

struct CreateView: View {
    @Environment(AppModel.self) private var model
    @State private var prompt = ""
    @State private var duration = 10
    @State private var style: AudiobookStyle = .cinematicDocumentary
    @State private var isSubmitting = false
    @State private var submissionError: String?
    @State private var createdID: String?
    @FocusState private var promptFocused: Bool

    private let durations = [5, 10, 15]
    private let inspirations = [
        "The mysteries of the deep ocean",
        "The Fermi Paradox, told as a cinematic mystery",
        "The hidden history of an ancient city",
        "How music changes the brain"
    ]
    private var trimmedPrompt: String { prompt.trimmingCharacters(in: .whitespacesAndNewlines) }
    private var canSubmit: Bool { (10...2000).contains(trimmedPrompt.utf16.count) && !isSubmitting }

    var body: some View {
        ZStack {
            FabletScreenBackground()
            ScrollView {
                VStack(alignment: .leading, spacing: 30) {
                    header
                    promptSection
                    durationSection
                    styleSection
                    submitSection
                }
                .padding(.horizontal, 22)
                .padding(.top, 20)
                .padding(.bottom, 36)
            }
            .scrollDismissesKeyboard(.interactively)
        }
        .toolbar(.hidden, for: .navigationBar)
        .preferredColorScheme(.dark)
        .navigationDestination(item: $createdID) { id in
            ProductionDetailView(id: id)
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                FabletEyebrow(text: "The beginning of a story")
                Spacer()
                FabletDemoBadge(mode: model.repositoryMode)
            }
            Text("Every great story starts with curiosity.")
                .font(.system(.largeTitle, design: .serif, weight: .medium))
                .foregroundStyle(FabletColors.ink)
                .fixedSize(horizontal: false, vertical: true)
            Text("Tell us what fascinates you. We'll bring it to life.")
                .font(.body)
                .foregroundStyle(FabletColors.muted)
        }
    }

    private var promptSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            FabletSectionHeading(title: "What are you curious about?", subtitle: "The more detail you share, the more personal your story.")
            ZStack(alignment: .topLeading) {
                if prompt.isEmpty {
                    Text("A forgotten moment in history, the mysteries of the ocean, how a city came to be…")
                        .font(.body)
                        .foregroundStyle(FabletColors.muted.opacity(0.72))
                        .padding(.horizontal, 17)
                        .padding(.vertical, 20)
                        .allowsHitTesting(false)
                }
                TextEditor(text: $prompt)
                    .font(.body)
                    .foregroundStyle(FabletColors.ink)
                    .scrollContentBackground(.hidden)
                    .focused($promptFocused)
                    .padding(12)
                    .frame(minHeight: 165)
                    .accessibilityLabel("What are you curious about?")
                    .accessibilityHint("Enter between 10 and 2000 characters.")
            }
            .fabletCard()
            HStack {
                Text("10–2,000 characters")
                Spacer()
                Text("\(trimmedPrompt.utf16.count) / 2,000")
                    .foregroundStyle(trimmedPrompt.utf16.count > 2000 ? FabletColors.danger : FabletColors.muted)
            }
            .font(.caption)
            .foregroundStyle(FabletColors.muted)
            VStack(alignment: .leading, spacing: 10) {
                FabletEyebrow(text: "Need inspiration?")
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(inspirations, id: \.self) { idea in
                            Button {
                                prompt = idea
                                promptFocused = true
                            } label: {
                                Text(idea)
                                    .font(.caption.weight(.medium))
                                    .foregroundStyle(FabletColors.ink)
                                    .padding(.horizontal, 14)
                                    .padding(.vertical, 10)
                                    .background(FabletColors.violet.opacity(0.14), in: Capsule())
                                    .overlay(Capsule().stroke(FabletColors.violet.opacity(0.3), lineWidth: 1))
                            }
                            .buttonStyle(.plain)
                            .accessibilityHint("Replaces the current prompt with this idea.")
                        }
                    }
                }
            }
        }
    }

    private var durationSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            FabletSectionHeading(title: "Length", subtitle: "Choose the time you'd like to spend.")
            HStack(spacing: 10) {
                ForEach(durations, id: \.self) { minutes in
                    Button {
                        duration = minutes
                    } label: {
                        Text("\(minutes) min")
                            .font(.subheadline.weight(.semibold))
                            .frame(maxWidth: .infinity, minHeight: 50)
                            .foregroundStyle(duration == minutes ? FabletColors.background : FabletColors.ink)
                            .background(duration == minutes ? FabletColors.accent : FabletColors.surface, in: RoundedRectangle(cornerRadius: 14))
                            .overlay(RoundedRectangle(cornerRadius: 14).stroke(FabletColors.line, lineWidth: 1))
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(duration == minutes ? .isSelected : [])
                }
            }
        }
    }

    private var styleSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            FabletSectionHeading(title: "Set the tone", subtitle: "Pick the way your story unfolds.")
            ForEach(AudiobookStyle.allCases) { option in
                Button {
                    style = option
                } label: {
                    HStack(spacing: 14) {
                        Image(systemName: option == .cinematicDocumentary ? "waveform.path" : "wind")
                            .font(.title3)
                            .foregroundStyle(FabletColors.accent)
                            .frame(width: 42, height: 42)
                            .background(FabletColors.accent.opacity(0.1), in: RoundedRectangle(cornerRadius: 13))
                        VStack(alignment: .leading, spacing: 4) {
                            Text(option.title).font(.subheadline.weight(.semibold)).foregroundStyle(FabletColors.ink)
                            Text(option.subtitle).font(.caption).foregroundStyle(FabletColors.muted)
                        }
                        Spacer(minLength: 8)
                        Image(systemName: style == option ? "checkmark.circle.fill" : "circle")
                            .foregroundStyle(style == option ? FabletColors.accent : FabletColors.muted)
                    }
                    .padding(16)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(FabletColors.surface, in: RoundedRectangle(cornerRadius: 18))
                    .overlay(RoundedRectangle(cornerRadius: 18).stroke(style == option ? FabletColors.accent.opacity(0.65) : FabletColors.line, lineWidth: 1))
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(style == option ? .isSelected : [])
            }
        }
    }

    private var submitSection: some View {
        VStack(spacing: 12) {
            if let submissionError {
                FabletErrorBanner(message: submissionError)
            }
            Button {
                promptFocused = false
                Task { await createProduction() }
            } label: {
                HStack(spacing: 9) {
                    if isSubmitting { ProgressView().tint(FabletColors.background) }
                    Text(isSubmitting ? "Creating your production…" : "Create my audiobook")
                    if !isSubmitting { Image(systemName: "arrow.right") }
                }
            }
            .buttonStyle(FabletPrimaryButtonStyle())
            .disabled(!canSubmit)
            .opacity(canSubmit ? 1 : 0.55)
            Text("Made with care, in the background. Your story will appear in your library.")
                .font(.caption)
                .foregroundStyle(FabletColors.muted)
                .multilineTextAlignment(.center)
        }
    }

    @MainActor
    private func createProduction() async {
        guard canSubmit else { return }
        isSubmitting = true
        submissionError = nil
        defer { isSubmitting = false }
        do {
            let id = try await model.create(prompt: trimmedPrompt, duration: duration, style: style)
            createdID = id
            prompt = ""
        } catch {
            submissionError = error.localizedDescription
        }
    }
}
