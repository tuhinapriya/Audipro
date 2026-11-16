import SwiftUI

struct HomeView: View {
    @Environment(AppModel.self) private var model
    @State private var prompt = ""
    @State private var submitting = false
    @State private var style: AudiobookStyle = .cinematicScene
    @State private var submissionError: String?
    @State private var createdID: String?
    @FocusState private var promptFocused: Bool

    private var trimmedPrompt: String { prompt.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        ZStack {
            FabletScreenBackground()
            ScrollView {
                VStack(alignment: .leading, spacing: 28) {
                    Text("fablet")
                        .font(.system(size: 27, weight: .medium, design: .serif))
                        .foregroundStyle(FabletColors.ink)
                    VStack(alignment: .leading, spacing: 9) {
                        Text("What would you like to hear?")
                            .font(.system(.largeTitle, design: .serif, weight: .medium))
                            .foregroundStyle(FabletColors.ink)
                        Text("Describe a story, a question, or a world to explore.")
                            .font(.subheadline).foregroundStyle(FabletColors.muted)
                    }
                    HStack(spacing: 8) {
                        ForEach([AudiobookStyle.cinematicScene, .cinematicDocumentary]) { option in
                            Button { style = option } label: {
                                Text(option == .cinematicScene ? "Scene" : "Documentary")
                                    .font(.subheadline.weight(.medium))
                                    .foregroundStyle(style == option ? FabletColors.background : FabletColors.ink)
                                    .padding(.horizontal, 16).padding(.vertical, 10)
                                    .background(style == option ? FabletColors.accent : FabletColors.surface, in: Capsule())
                            }.buttonStyle(.plain)
                        }
                    }
                    composer
                    recents
                }
                .padding(.horizontal, 22).padding(.top, 24).padding(.bottom, 36)
            }
            .scrollDismissesKeyboard(.interactively)
            .refreshable { await model.refresh() }
        }
        .toolbar(.hidden, for: .navigationBar)
        .navigationDestination(item: $createdID) { id in ProductionDetailView(id: id) }
    }

    private var composer: some View {
        VStack(alignment: .leading, spacing: 14) {
            ZStack(alignment: .topLeading) {
                if prompt.isEmpty {
                    Text("Tell me about the deep ocean in 3 minutes…")
                        .foregroundStyle(FabletColors.muted.opacity(0.8))
                        .padding(.horizontal, 5).padding(.vertical, 8)
                        .allowsHitTesting(false)
                }
                TextEditor(text: $prompt)
                    .scrollContentBackground(.hidden)
                    .foregroundStyle(FabletColors.ink)
                    .frame(minHeight: 120)
                    .focused($promptFocused)
                    .accessibilityLabel("Describe what you want to hear")
            }
            HStack(alignment: .center) {
                Text("About 1 minute by default")
                    .font(.caption).foregroundStyle(FabletColors.muted)
                Spacer()
                Button { Task { await submit() } } label: {
                    if submitting { ProgressView().tint(FabletColors.background).frame(width: 46, height: 46) }
                    else { Image(systemName: "arrow.up").font(.headline).foregroundStyle(FabletColors.background).frame(width: 46, height: 46) }
                }
                .background(FabletColors.accent, in: Circle())
                .disabled(submitting || !(10...2000).contains(trimmedPrompt.utf16.count))
                .opacity(submitting || !(10...2000).contains(trimmedPrompt.utf16.count) ? 0.5 : 1)
                .accessibilityLabel("Create audio")
            }
            if let submissionError { Text(submissionError).font(.caption).foregroundStyle(FabletColors.danger) }
        }
        .padding(16).fabletCard()
    }

    private var recents: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Recents").font(.system(.title2, design: .serif, weight: .medium)).foregroundStyle(FabletColors.ink)
                Spacer()
                if !model.productions.isEmpty {
                    Button("Library") { model.selectedTab = .library }
                        .font(.subheadline.weight(.medium)).foregroundStyle(FabletColors.accent)
                }
            }
            if let error = model.error, !error.isEmpty { FabletErrorBanner(message: error) }
            if model.isLoading && model.productions.isEmpty { ProgressView().tint(FabletColors.accent) }
            else if model.productions.isEmpty {
                Text("Your recent stories will appear here.").font(.subheadline).foregroundStyle(FabletColors.muted).padding(.vertical, 8)
            } else {
                ForEach(Array(model.productions.prefix(3))) { production in
                    NavigationLink(value: production.id) { FabletProductionRow(production: production) }.buttonStyle(.plain)
                }
            }
        }
    }

    private func submit() async {
        guard !submitting else { return }
        submitting = true
        submissionError = nil
        defer { submitting = false }
        do {
            let duration = try requestedDuration(in: trimmedPrompt)
            let id = try await model.create(prompt: trimmedPrompt, duration: duration, style: style)
            prompt = ""
            promptFocused = false
            createdID = id
        } catch { submissionError = error.localizedDescription }
    }
}
