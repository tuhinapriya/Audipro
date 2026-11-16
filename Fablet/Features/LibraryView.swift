import SwiftUI

struct LibraryView: View {
    @Environment(AppModel.self) private var model
    @State private var openingID: String?
    @State private var filter: LibraryFilter = .all

    private enum LibraryFilter: String, CaseIterable {
        case all = "All"
        case inProgress = "In Production"
        case completed = "Ready to Listen"
        case failed = "Failed"
    }

    private var filteredProductions: [Production] {
        model.productions.filter { production in
            switch filter {
            case .all: return true
            case .inProgress: return production.status != .completed && production.status != .failed
            case .completed: return production.status == .completed
            case .failed: return production.status == .failed
            }
        }
    }

    var body: some View {
        ZStack {
            FabletScreenBackground()
            ScrollView {
                VStack(alignment: .leading, spacing: 25) {
                    header
                    if let error = model.error, !error.isEmpty {
                        FabletErrorBanner(message: error)
                    }
                    filters
                    if model.isLoading && model.productions.isEmpty {
                        ProgressView("Loading your library")
                            .tint(FabletColors.accent)
                            .foregroundStyle(FabletColors.muted)
                            .frame(maxWidth: .infinity, minHeight: 180)
                    } else if model.productions.isEmpty && (model.error == nil || model.error?.isEmpty == true) {
                        emptyState
                    } else if model.productions.isEmpty {
                        Text("Your library could not be loaded. Pull to refresh.")
                            .font(.subheadline)
                            .foregroundStyle(FabletColors.muted)
                    } else if filteredProductions.isEmpty {
                        Text("No productions in this filter yet.")
                            .font(.subheadline)
                            .foregroundStyle(FabletColors.muted)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(20)
                            .fabletCard()
                    } else {
                        productionList
                    }
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

    private var filters: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(LibraryFilter.allCases, id: \.self) { option in
                    Button { filter = option } label: {
                        Text(option.rawValue)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(filter == option ? FabletColors.background : FabletColors.ink)
                            .padding(.horizontal, 15)
                            .padding(.vertical, 10)
                            .background(filter == option ? FabletColors.accent : FabletColors.surface, in: Capsule())
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(filter == option ? .isSelected : [])
                }
            }
        }
        .accessibilityLabel("Filter productions")
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                FabletEyebrow(text: "Your collection")
                Spacer()
                FabletDemoBadge(mode: model.repositoryMode)
            }
            Text("Your Library")
                .font(.system(.largeTitle, design: .serif, weight: .medium))
                .foregroundStyle(FabletColors.ink)
            Text("Every curiosity, beautifully told.")
                .font(.body)
                .foregroundStyle(FabletColors.muted)
        }
    }

    private var emptyState: some View {
        VStack(alignment: .leading, spacing: 18) {
            Image(systemName: "books.vertical")
                .font(.system(size: 28, weight: .light))
                .foregroundStyle(FabletColors.accent)
                .frame(width: 58, height: 58)
                .background(FabletColors.accent.opacity(0.1), in: RoundedRectangle(cornerRadius: 18))
            VStack(alignment: .leading, spacing: 8) {
                Text("Your next favorite story hasn't been created yet.")
                    .font(.system(.title2, design: .serif, weight: .medium))
                    .foregroundStyle(FabletColors.ink)
                Text("Your productions, in progress and complete, will live here.")
                    .font(.subheadline)
                    .foregroundStyle(FabletColors.muted)
            }
            Button("Create Your First Audiobook") { model.selectedTab = .create }
                .buttonStyle(FabletPrimaryButtonStyle())
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(22)
        .fabletCard()
    }

    private var productionList: some View {
        LazyVStack(alignment: .leading, spacing: 14) {
            FabletSectionHeading(title: filter == .all ? "All productions" : filter.rawValue, subtitle: "From first idea to finished listen.")
                .padding(.bottom, 3)
            ForEach(filteredProductions) { production in
                VStack(alignment: .leading, spacing: 0) {
                    NavigationLink(value: production.id) {
                        FabletProductionRow(production: production)
                    }
                    .buttonStyle(.plain)

                    if production.status == .completed && production.assetsAvailable {
                        Button {
                            Task {
                                guard openingID == nil else { return }
                                openingID = production.id
                                await model.openPlayer(production)
                                openingID = nil
                            }
                        } label: {
                            HStack(spacing: 7) {
                                if openingID == production.id {
                                    ProgressView().tint(FabletColors.accent)
                                } else {
                                    Image(systemName: "play.fill")
                                }
                                Text(openingID == production.id ? "Opening player…" : "Play")
                            }
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(FabletColors.accent)
                            .padding(.vertical, 12)
                            .padding(.horizontal, 15)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .disabled(openingID != nil)
                        .accessibilityLabel("Play \(fabletProductionTitle(production))")
                    }
                }
            }
        }
    }
}
