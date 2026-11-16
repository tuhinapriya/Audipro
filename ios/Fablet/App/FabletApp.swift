import SwiftUI

@main
struct FabletApp: App {
    @State private var model = AppModel()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            FabletRootView()
                .environment(model)
                .onChange(of: scenePhase) { _, phase in
                    if phase == .active { Task { await model.refresh() } }
                }
        }
    }
}

private struct FabletRootView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Group {
            if let message = model.configurationError {
                gate(title: "Setup needed", message: message)
            } else if model.isRestoring {
                ZStack {
                    FabletScreenBackground()
                    ProgressView("Restoring your session").tint(FabletColors.accent).foregroundStyle(FabletColors.ink)
                }
            } else if !model.isAuthenticated {
                signIn
            } else {
                tabs
            }
        }
        .preferredColorScheme(.dark)
    }

    private var signIn: some View {
        ZStack {
            FabletScreenBackground()
            VStack(alignment: .leading, spacing: 20) {
                FabletEyebrow(text: "Fablet · your private library")
                Text("Stories begin with curiosity.")
                    .font(.system(.largeTitle, design: .serif, weight: .medium))
                    .foregroundStyle(FabletColors.ink)
                Text("Sign in to create and follow your audiobooks across sessions.")
                    .foregroundStyle(FabletColors.muted)
                if let error = model.authError { FabletErrorBanner(message: error) }
                Button {
                    Task { await model.signIn() }
                } label: {
                    HStack {
                        if model.isSigningIn { ProgressView().tint(FabletColors.background) }
                        Text(model.isSigningIn ? "Signing in…" : "Sign in with Auth0")
                    }
                }
                .buttonStyle(FabletPrimaryButtonStyle())
                .disabled(model.isSigningIn)
            }
            .padding(24)
            .frame(maxWidth: 500)
        }
    }

    private func gate(title: String, message: String) -> some View {
        ZStack {
            FabletScreenBackground()
            VStack(alignment: .leading, spacing: 16) {
                Text(title).font(.title.bold()).foregroundStyle(FabletColors.ink)
                FabletErrorBanner(message: message)
            }.padding(24)
        }
    }

    private var tabs: some View {
        @Bindable var model = model
        return VStack(spacing: 0) {
            if model.repositoryMode == "Demo" {
                Text("Demo · Saved locally only. Jobs stay queued; no audio is generated.")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(FabletColors.ink)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: .infinity)
                    .padding(10)
                    .background(FabletColors.surfaceRaised)
            }
            TabView(selection: $model.selectedTab) {
                NavigationStack {
                    HomeView().navigationDestination(for: String.self) { DetailDestination(id: $0) }
                }.tabItem { Label("Home", systemImage: "house") }.tag(AppTab.home)
                NavigationStack {
                    LibraryView().navigationDestination(for: String.self) { DetailDestination(id: $0) }
                }.tabItem { Label("Library", systemImage: "books.vertical") }.tag(AppTab.library)
            }
            .tint(FabletColors.accent)
        }
        .background(FabletColors.background)
        .sheet(isPresented: Binding(
            get: { model.player.isPresented },
            set: { model.player.isPresented = $0 }
        )) { AudiobookPlayerView() }
    }
}

private struct DetailDestination: View {
    let id: String
    @Environment(AppModel.self) private var model
    var body: some View {
        ProductionDetailView(id: id)
            .onAppear { model.watchProduction(id: id) }
    }
}