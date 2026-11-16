import Foundation
import SwiftUI

struct ProductionDetailView: View {
    let id: String
    @Environment(AppModel.self) private var model
    @State private var openingPlayer = false
    @State private var isCheckingProduction = true
    private var isSample: Bool { model.repositoryMode == "Demo" && id == DemoProductionRepository.sampleID }

    private let stages: [ProductionStatus] = [
        .queued, .researching, .writing, .narrating, .scoring, .mixing, .qualityCheck, .completed
    ]

    var body: some View {
        ZStack {
            FabletScreenBackground()
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    HStack {
                        FabletEyebrow(text: isSample ? "Pre-rendered sample" : "Your production")
                        Spacer()
                        FabletDemoBadge(mode: model.repositoryMode)
                    }
                    if !isSample {
                        VStack(alignment: .leading, spacing: 4) {
                            FabletEyebrow(text: "Production ID")
                            Text(id)
                                .font(.caption.monospaced())
                                .foregroundStyle(FabletColors.muted)
                                .textSelection(.enabled)
                        }
                    }
                    if let production = model.production(id: id) {
                        productionContent(production)
                    } else if isCheckingProduction || model.isLoading {
                        ProgressView("Loading production")
                            .tint(FabletColors.accent)
                            .foregroundStyle(FabletColors.muted)
                            .frame(maxWidth: .infinity, minHeight: 180)
                    } else if model.error == nil || model.error?.isEmpty == true {
                        unavailableContent
                    } else {
                        Text("Unable to check this production. Refresh to try again.")
                            .font(.subheadline)
                            .foregroundStyle(FabletColors.muted)
                    }
                    if let error = model.error, !error.isEmpty {
                        FabletErrorBanner(message: error)
                    }
                }
                .padding(.horizontal, 22)
                .padding(.top, 18)
                .padding(.bottom, 36)
            }
            .refreshable { await model.refresh() }
        }
        .navigationTitle("Production")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.visible, for: .navigationBar)
        .toolbarBackground(FabletColors.background, for: .navigationBar)
        .toolbarBackground(.visible, for: .navigationBar)
        .preferredColorScheme(.dark)
        .task(id: id) {
            isCheckingProduction = true
            await model.refresh()
            isCheckingProduction = false
        }
    }

    private func productionContent(_ production: Production) -> some View {
        VStack(alignment: .leading, spacing: 24) {
            FabletArtwork(large: true, production: production)
                .frame(maxWidth: 310)
                .frame(maxWidth: .infinity)

            VStack(alignment: .leading, spacing: 12) {
                FabletStatusPill(production: production)
                Text(fabletProductionTitle(production))
                    .font(.system(.largeTitle, design: .serif, weight: .medium))
                    .foregroundStyle(FabletColors.ink)
                    .fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 10) {
                    Label(fabletDuration(production), systemImage: "clock")
                    Text("·")
                    Text(production.style.title)
                }
                .font(.caption.weight(.medium))
                .foregroundStyle(FabletColors.muted)
            }

            if production.status == .completed {
                completedContent(production)
            } else if production.status == .failed {
                failedContent(production)
            } else {
                progressContent(production)
            }

            if !isSample { productionTimeline(production) }

            if let description = production.description?.trimmingCharacters(in: .whitespacesAndNewlines), !description.isEmpty {
                VStack(alignment: .leading, spacing: 9) {
                    FabletSectionHeading(title: "About this story")
                    Text(description)
                        .font(.body)
                        .foregroundStyle(FabletColors.muted)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            if !isSample {
                VStack(alignment: .leading, spacing: 9) {
                    FabletEyebrow(text: "The original idea")
                    Text(production.prompt)
                        .font(.subheadline)
                        .foregroundStyle(FabletColors.ink.opacity(0.85))
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .padding(18)
                .fabletCard()
            }
        }
    }

    private func productionTimeline(_ production: Production) -> some View {
        VStack(alignment: .leading, spacing: 15) {
            FabletSectionHeading(title: "Production timeline", subtitle: "The current stage is reported by the production service.")
            ForEach(stages.indices, id: \.self) { index in
                let stage = stages[index]
                let isCurrent = production.status == stage
                HStack(spacing: 12) {
                    Image(systemName: isCurrent ? "largecircle.fill.circle" : "circle")
                        .foregroundStyle(isCurrent ? FabletColors.accent : FabletColors.muted.opacity(0.5))
                    Text(stage.label)
                        .foregroundStyle(isCurrent ? FabletColors.ink : FabletColors.muted)
                    Spacer()
                    if isCurrent {
                        Text(stage == .completed ? "Complete" : "Current")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(FabletColors.accent)
                    }
                }
                .font(.subheadline)
                .accessibilityElement(children: .combine)
            }
            if production.status == .failed {
                Label("Failed", systemImage: "exclamationmark.circle.fill")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(FabletColors.danger)
            }
            Text("Other stages are shown for context; individual stage history is not available.")
                .font(.caption)
                .foregroundStyle(FabletColors.muted)
        }
        .padding(20)
        .fabletCard()
    }

    private func progressContent(_ production: Production) -> some View {
        VStack(alignment: .leading, spacing: 17) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 6) {
                    FabletEyebrow(text: "In production")
                    Text(production.status == .queued ? "In the production queue" : production.status.label)
                        .font(.system(.title3, design: .serif, weight: .medium))
                        .foregroundStyle(FabletColors.ink)
                    Text(fabletStageMessage(production))
                        .font(.subheadline)
                        .foregroundStyle(FabletColors.muted)
                }
                Spacer(minLength: 8)
                Text(progressText(production.progressPercent))
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(FabletColors.accent)
            }
            FabletProgressBar(percent: production.progressPercent)
            Text("This is a quality-first production; your audiobook will appear here when ready.")
                .font(.caption)
                .foregroundStyle(FabletColors.muted)
            Text("Progress reflects reported production milestones, not a time estimate.")
                .font(.caption2)
                .foregroundStyle(FabletColors.muted)
        }
        .padding(20)
        .fabletCard()
    }

    private func completedContent(_ production: Production) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            if production.assetsAvailable {
                Button {
                    Task {
                        guard !openingPlayer else { return }
                        openingPlayer = true
                        await model.openPlayer(production)
                        openingPlayer = false
                    }
                } label: {
                    HStack(spacing: 9) {
                        if openingPlayer {
                            ProgressView().tint(FabletColors.background)
                        } else {
                            Image(systemName: "play.fill")
                        }
                        Text(openingPlayer ? "Opening player…" : "Listen now")
                    }
                }
                .buttonStyle(FabletPrimaryButtonStyle())
                .disabled(openingPlayer)
            } else {
                Label("Audio assets aren't available yet.", systemImage: "exclamationmark.circle")
                    .font(.subheadline)
                    .foregroundStyle(FabletColors.muted)
                    .padding(18)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .fabletCard()
            }
        }
    }

    private func failedContent(_ production: Production) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            Label("Production couldn't be completed", systemImage: "exclamationmark.circle")
                .font(.headline)
                .foregroundStyle(FabletColors.danger)
            Text(failureMessage(production))
                .font(.subheadline)
                .foregroundStyle(FabletColors.muted)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(20)
        .fabletCard()
    }

    private var unavailableContent: some View {
        VStack(alignment: .leading, spacing: 14) {
            Image(systemName: "waveform.slash")
                .font(.title)
                .foregroundStyle(FabletColors.accent)
            Text("Production unavailable")
                .font(.system(.title2, design: .serif, weight: .medium))
                .foregroundStyle(FabletColors.ink)
            Text("This production couldn't be found. Refresh to check again.")
                .font(.subheadline)
                .foregroundStyle(FabletColors.muted)
            Button("Refresh") { Task { await model.refresh() } }
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(FabletColors.accent)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(20)
        .fabletCard()
    }

    private func progressText(_ value: Double) -> String {
        guard value.isFinite else { return "—" }
        return "\(Int(min(max(value, 0), 100).rounded()))%"
    }

    private func failureMessage(_ production: Production) -> String {
        let message = production.errorMessage?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return message.isEmpty ? "Something went wrong while making this production." : message
    }
}
