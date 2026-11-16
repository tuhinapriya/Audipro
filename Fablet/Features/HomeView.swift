import SwiftUI

struct HomeView: View {
    @Environment(AppModel.self) private var model
    @State private var openingID: String?
    @AppStorage("fablet.player.lastProductionID") private var lastProductionID = ""
    @AppStorage("fablet.player.position") private var lastPosition = 0.0

    private var completedProductions: [Production] {
        model.productions.filter { $0.status == .completed }
    }

    private var continueProduction: Production? {
        guard !lastProductionID.isEmpty else { return nil }
        return model.productions.first { $0.id == lastProductionID && $0.status == .completed && $0.assetsAvailable }
    }

    var body: some View {
        ZStack {
            FabletScreenBackground()
            ScrollView {
                VStack(alignment: .leading, spacing: 30) {
                    header
                    introduction
                    createCard
                    if let production = continueProduction {
                        continueListening(production)
                    }
                    featuredProductions
                    recentProductions
                }
                .padding(.horizontal, 22)
                .padding(.top, 20)
                .padding(.bottom, 36)
            }
            .refreshable { await model.refresh() }
        }
        .toolbar(.hidden, for: .navigationBar)
        .preferredColorScheme(.dark)
    }

    private func continueListening(_ production: Production) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            FabletSectionHeading(title: "Continue listening", subtitle: "Pick up your last audiobook.")
            HStack(spacing: 14) {
                FabletArtwork(production: production).frame(width: 76)
                VStack(alignment: .leading, spacing: 6) {
                    Text(fabletProductionTitle(production))
                        .font(.system(.headline, design: .serif, weight: .medium))
                        .foregroundStyle(FabletColors.ink)
                        .lineLimit(2)
                    Text(fabletDuration(production))
                        .font(.caption)
                        .foregroundStyle(FabletColors.muted)
                    if let duration = production.durationSeconds, duration > 0 {
                        FabletProgressBar(percent: min(100, max(0, lastPosition / duration * 100)))
                    }
                }
                Spacer(minLength: 0)
                Button {
                    Task {
                        guard openingID == nil else { return }
                        openingID = production.id
                        await model.openPlayer(production)
                        openingID = nil
                    }
                } label: {
                    Group {
                        if openingID == production.id {
                            ProgressView().tint(FabletColors.background)
                        } else {
                            Image(systemName: "play.fill")
                        }
                    }
                    .foregroundStyle(FabletColors.background)
                    .frame(width: 44, height: 44)
                    .background(FabletColors.accent, in: Circle())
                }
                .buttonStyle(.plain)
                .disabled(openingID != nil)
                .accessibilityLabel("Continue listening to \(fabletProductionTitle(production))")
            }
            .padding(16)
            .fabletCard()
        }
    }

    private var featuredProductions: some View {
        VStack(alignment: .leading, spacing: 16) {
            FabletSectionHeading(title: "Featured listens", subtitle: "Previously completed productions from your library.")
            if model.isLoading && model.productions.isEmpty {
                ProgressView("Loading featured listens")
                    .tint(FabletColors.accent)
                    .foregroundStyle(FabletColors.muted)
            } else if completedProductions.isEmpty {
                Text(model.error == nil || model.error?.isEmpty == true
                     ? "Completed productions will appear here when they're ready."
                     : "Featured listens could not be loaded.")
                    .font(.subheadline)
                    .foregroundStyle(FabletColors.muted)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(18)
                    .fabletCard()
            } else {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(alignment: .top, spacing: 14) {
                        ForEach(Array(completedProductions.prefix(5))) { production in
                            NavigationLink(value: production.id) {
                                VStack(alignment: .leading, spacing: 9) {
                                    FabletArtwork(production: production)
                                    Text(fabletProductionTitle(production))
                                        .font(.system(.headline, design: .serif, weight: .medium))
                                        .foregroundStyle(FabletColors.ink)
                                        .lineLimit(2)
                                        .multilineTextAlignment(.leading)
                                    Text(fabletDuration(production))
                                        .font(.caption)
                                        .foregroundStyle(FabletColors.muted)
                                    FabletStatusPill(production: production)
                                }
                                .frame(width: 160, alignment: .leading)
                                .padding(12)
                                .fabletCard()
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
        }
    }

    private var header: some View {
        HStack(alignment: .center) {
            HStack(spacing: 9) {
                Image(systemName: "waveform.circle")
                    .font(.system(size: 25, weight: .light))
                    .foregroundStyle(FabletColors.accent)
                Text("fablet")
                    .font(.system(size: 25, weight: .medium, design: .serif))
                    .tracking(-0.8)
                    .foregroundStyle(FabletColors.ink)
            }
            Spacer()
            FabletDemoBadge(mode: model.repositoryMode)
        }
        .accessibilityElement(children: .combine)
    }

    private var introduction: some View {
        VStack(alignment: .leading, spacing: 12) {
            FabletEyebrow(text: "A studio for the curious")
            Text("What are you\ncurious about?")
                .font(.system(.largeTitle, design: .serif, weight: .medium))
                .foregroundStyle(FabletColors.ink)
                .fixedSize(horizontal: false, vertical: true)
            Text("Turn any idea into a beautifully narrated audio documentary.")
                .font(.body)
                .foregroundStyle(FabletColors.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var createCard: some View {
        VStack(alignment: .leading, spacing: 22) {
            HStack(alignment: .top) {
                Image(systemName: "sparkles")
                    .font(.title3.weight(.light))
                    .foregroundStyle(FabletColors.accent)
                    .frame(width: 48, height: 48)
                    .background(FabletColors.accent.opacity(0.1), in: RoundedRectangle(cornerRadius: 15))
                Spacer()
                FabletEyebrow(text: "Your next listen")
            }
            VStack(alignment: .leading, spacing: 7) {
                Text("Every great story starts with a question.")
                    .font(.system(.title2, design: .serif, weight: .medium))
                    .foregroundStyle(FabletColors.ink)
                Text("Share an idea and we'll create an original audio production for you.")
                    .font(.subheadline)
                    .foregroundStyle(FabletColors.muted)
            }
            Button {
                model.selectedTab = .create
            } label: {
                HStack {
                    Text("Create a Story")
                    Image(systemName: "arrow.right")
                }
            }
            .buttonStyle(FabletPrimaryButtonStyle())
        }
        .padding(22)
        .background(
            LinearGradient(colors: [FabletColors.surfaceRaised, FabletColors.surface], startPoint: .topLeading, endPoint: .bottomTrailing),
            in: RoundedRectangle(cornerRadius: 24)
        )
        .overlay(RoundedRectangle(cornerRadius: 24).stroke(FabletColors.line, lineWidth: 1))
    }

    private var recentProductions: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .firstTextBaseline) {
                FabletSectionHeading(title: "Your recent stories", subtitle: "Follow along from idea to audio.")
                Spacer()
                if !model.productions.isEmpty {
                    Button("See all") { model.selectedTab = .library }
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(FabletColors.accent)
                }
            }
            if let error = model.error, !error.isEmpty {
                FabletErrorBanner(message: error)
            }
            if model.isLoading && model.productions.isEmpty {
                ProgressView("Loading your stories")
                    .tint(FabletColors.accent)
                    .foregroundStyle(FabletColors.muted)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 15)
            } else if model.productions.isEmpty && (model.error == nil || model.error?.isEmpty == true) {
                Text("Your productions will find a home here.")
                    .font(.subheadline)
                    .foregroundStyle(FabletColors.muted)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(20)
                    .fabletCard()
            } else if !model.productions.isEmpty {
                ForEach(Array(model.productions.prefix(3))) { production in
                    NavigationLink(value: production.id) {
                        FabletProductionRow(production: production)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }
}
