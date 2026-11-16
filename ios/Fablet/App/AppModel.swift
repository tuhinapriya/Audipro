import Auth0
import Combine
import ConvexAuth0
import ConvexMobile
import Foundation
import Observation
import UIKit

enum AppTab: Hashable { case home, library }

@Observable @MainActor
final class AppModel {
    var productions: [Production] = []
    var selectedTab: AppTab = .home
    let player = AudioPlayerService()
    private(set) var covers: [String: UIImage] = [:]
    private(set) var repositoryMode = "Demo"
    private(set) var isAuthenticated = false
    private(set) var isRestoring = false
    private(set) var isSigningIn = false
    private(set) var configurationError: String?
    private(set) var authError: String?
    private var listLoading = false
    private var detailLoading = false
    private var listError: String?
    private var detailError: String?
    private var detailID: String?
    private var details: [String: DetailState] = [:]

    private struct DetailState {
        var production: Production?
        var loaded = false
        var loading = false
        var failed = false
    }

    var isLoading: Bool { listLoading || detailLoading }
    var error: String? { detailError ?? listError }

    @ObservationIgnored private var repository: (any ProductionRepository)?
    @ObservationIgnored private var client: ConvexClientWithAuth<Credentials>?
    @ObservationIgnored private var authSubscription: AnyCancellable?
    @ObservationIgnored private var listSubscription: AnyCancellable?
    @ObservationIgnored private var detailSubscriptions: [String: AnyCancellable] = [:]
    @ObservationIgnored private var listGeneration = UUID()
    @ObservationIgnored private var detailGenerations: [String: UUID] = [:]
    @ObservationIgnored private var coverRequests: Set<String> = []
    @ObservationIgnored private var coverFailures: [String: Date] = [:]
    @ObservationIgnored private var coverSession = UUID()

    init(configuration: FabletConfiguration = .load()) {
        switch configuration {
        case .demo:
            #if targetEnvironment(simulator)
            if ProcessInfo.processInfo.arguments.contains("--local-generator") {
                repository = LocalGeneratorRepository()
                repositoryMode = "Local generator"
            } else {
                repository = DemoProductionRepository()
            }
            #else
            repository = DemoProductionRepository()
            #endif
            isAuthenticated = true
            startList()
        case .invalid(let message):
            repositoryMode = "Configuration error"
            configurationError = message
        case .live(let deployment):
            repositoryMode = "Live"
            let client = ConvexClientWithAuth(deploymentUrl: deployment, authProvider: Auth0Provider())
            self.client = client
            repository = ConvexProductionRepository(client: client)
            isRestoring = true
            authSubscription = client.authState.receive(on: DispatchQueue.main).sink { [weak self] state in
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    switch state {
                    case .authenticated:
                        if !self.isAuthenticated {
                            self.isAuthenticated = true
                            self.authError = nil
                            self.startList()
                        }
                    case .unauthenticated:
                        if self.isAuthenticated { self.clearSession() }
                    case .loading: break
                    }
                }
            }
            Task { [weak self] in
                _ = await client.loginFromCache()
                self?.isRestoring = false
            }
        }
    }

    func signIn() async {
        guard let client, !isSigningIn else { return }
        isSigningIn = true
        authError = nil
        let result = await client.login()
        if case .failure = result { authError = "Sign-in was not completed. Please try again." }
        isSigningIn = false
    }

    func create(prompt: String, duration: Double, style: AudiobookStyle) async throws -> String {
        guard isAuthenticated, let repository else { throw AppError.signInRequired }
        let id = try await repository.create(prompt: prompt, duration: duration, style: style)
        watchProduction(id: id)
        return id
    }

    func production(id: String) -> Production? {
        if let state = details[id], state.loaded { return state.production }
        return productions.first { $0.id == id }
    }

    func watchProduction(id: String) {
        guard isAuthenticated, let repository else { return }
        for otherID in Array(detailSubscriptions.keys) where otherID != id {
            detailSubscriptions.removeValue(forKey: otherID)?.cancel()
            detailGenerations.removeValue(forKey: otherID)
            details.removeValue(forKey: otherID)
        }
        detailSubscriptions[id]?.cancel()
        let generation = UUID()
        detailGenerations[id] = generation
        detailID = id
        details[id] = DetailState(loading: true)
        detailError = nil
        detailLoading = true
        detailSubscriptions[id] = repository.get(id: id).receive(on: DispatchQueue.main).sink { [weak self] completion in
            Task { @MainActor [weak self] in
                guard let self, self.detailGenerations[id] == generation else { return }
                self.details[id]?.loading = false
                if case .failure = completion {
                    self.details[id]?.failed = true
                }
                self.updateDetailStatus()
            }
        } receiveValue: { [weak self] production in
            Task { @MainActor [weak self] in
                guard let self, self.detailGenerations[id] == generation else { return }
                self.details[id] = DetailState(production: production, loaded: true)
                self.updateDetailStatus()
            }
        }
    }

    private func updateDetailStatus() {
        let state = detailID.flatMap { details[$0] }
        detailLoading = state?.loading ?? false
        detailError = state?.failed == true ? "Couldn't load this production. Refresh to try again." : nil
    }

    func refresh() async {
        guard isAuthenticated else { return }
        startList()
        let current = detailID
        for id in Array(detailSubscriptions.keys) { watchProduction(id: id) }
        detailID = current
        updateDetailStatus()
    }

    func openPlayer(_ production: Production) async {
        guard isAuthenticated, let repository, production.status == .completed, production.assetsAvailable else { return }
        player.isPresented = true
        await player.open(production, using: repository)
    }

    func loadCover(_ production: Production) async {
        let id = production.id
        guard isAuthenticated, production.status == .completed, production.assetsAvailable,
              covers[id] == nil, !coverRequests.contains(id),
              (coverFailures[id]?.timeIntervalSinceNow ?? -1) <= 0,
              let repository else { return }
        coverRequests.insert(id)
        let session = coverSession
        defer { if session == coverSession { coverRequests.remove(id) } }
        do {
            let urls = try await repository.playbackURL(id: id)
            let (data, response) = try await URLSession.shared.data(from: urls.coverURL)
            guard session == coverSession, !Task.isCancelled,
                  let response = response as? HTTPURLResponse, (200...299).contains(response.statusCode),
                  let image = UIImage(data: data) else { throw RepositoryError.invalidResponse }
            covers[id] = image
            coverFailures[id] = nil
        } catch {
            if session == coverSession { coverFailures[id] = Date().addingTimeInterval(60) }
        }
    }

    private func startList() {
        guard let repository else { return }
        listSubscription?.cancel()
        listGeneration = UUID()
        let generation = listGeneration
        listLoading = true
        listError = nil
        listSubscription = repository.list().receive(on: DispatchQueue.main).sink { [weak self] completion in
            Task { @MainActor [weak self] in
                guard let self, self.listGeneration == generation else { return }
                self.listLoading = false
                if case .failure = completion {
                    self.listError = "Couldn't load your library. Refresh to try again."
                }
            }
        } receiveValue: { [weak self] productions in
            Task { @MainActor [weak self] in
                guard let self, self.listGeneration == generation else { return }
                self.productions = productions
                self.listLoading = false
                self.listError = nil
            }
        }
    }

    private func clearSession() {
        listGeneration = UUID()
        detailGenerations.removeAll()
        listSubscription?.cancel()
        detailSubscriptions.removeAll()
        productions = []
        details.removeAll()
        detailID = nil
        listLoading = false
        detailLoading = false
        listError = nil
        detailError = nil
        isAuthenticated = false
        coverSession = UUID()
        coverRequests.removeAll()
        coverFailures.removeAll()
        covers.removeAll()
        player.resetSession()
    }

    private enum AppError: LocalizedError {
        case signInRequired
        var errorDescription: String? { "Sign in before creating a production." }
    }
}