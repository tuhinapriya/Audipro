import Combine
import ConvexMobile
import Foundation

/// Wire numbers are JavaScript numbers, not Convex Int64 values. Decode them
/// using the SDK wrappers; the app's persistent Codable model stays SDK-free.
struct ConvexProduction: Decodable {
    let id: String
    let status: ProductionStatus
    @ConvexFloat var progressPercent: Double
    let stageMessage: String
    let createdAt: String
    let updatedAt: String
    let prompt: String
    @ConvexFloat var durationMinutesRequested: Double
    let style: AudiobookStyle
    let title: String?
    let description: String?
    @OptionalConvexFloat var durationSeconds: Double?
    let assetsAvailable: Bool
    let errorMessage: String?

    enum CodingKeys: String, CodingKey {
        case id, status, prompt, style, title, description
        case progressPercent = "progress_percent", stageMessage = "stage_message"
        case createdAt = "created_at", updatedAt = "updated_at"
        case durationMinutesRequested = "duration_minutes_requested"
        case durationSeconds = "duration_seconds", assetsAvailable = "assets_available"
        case errorMessage = "error_message"
    }

    func model() throws -> Production {
        guard durationMinutesRequested.isFinite, durationMinutesRequested >= 1.0 / 6.0,
              progressPercent.isFinite, durationSeconds.map({ $0.isFinite }) ?? true else {
            throw RepositoryError.invalidResponse
        }
        return Production(id: id, status: status, progressPercent: progressPercent,
            stageMessage: stageMessage, createdAt: createdAt, updatedAt: updatedAt, prompt: prompt,
            durationMinutesRequested: durationMinutesRequested, style: style, title: title,
            description: description, durationSeconds: durationSeconds, assetsAvailable: assetsAvailable,
            errorMessage: errorMessage)
    }
}

@MainActor
final class ConvexProductionRepository: ProductionRepository {
    private let client: ConvexClient
    init(client: ConvexClient) { self.client = client }

    func list() -> AnyPublisher<[Production], Error> {
        client.subscribe(to: "productions:list", yielding: [ConvexProduction].self)
            .tryMap { try $0.map { try $0.model() } }.eraseToAnyPublisher()
    }

    func get(id: String) -> AnyPublisher<Production?, Error> {
        client.subscribe(to: "productions:get", with: ["id": id], yielding: ConvexProduction?.self)
            .tryMap { try $0?.model() }.eraseToAnyPublisher()
    }

    func create(prompt: String, duration: Double, style: AudiobookStyle) async throws -> String {
        let prompt = try validateProductionInput(prompt: prompt, duration: duration)
        guard style != .cinematicScene else { throw RepositoryError.sceneUnavailable }
        let result: CreateResult = try await client.mutation("productions:create", with: [
            "prompt": prompt, "duration_minutes": Double(duration), "style": style.rawValue
        ])
        guard result.status == .queued, !result.id.isEmpty else { throw RepositoryError.invalidResponse }
        return result.id
    }

    func playbackURL(id: String) async throws -> PlaybackURLs {
        let result: PlaybackURLs = try await client.action("productions:getPlaybackUrl", with: ["id": id])
        guard result.audioURL.scheme == "https", result.coverURL.scheme == "https" else {
            throw RepositoryError.invalidResponse
        }
        return result
    }

    private struct CreateResult: Decodable {
        let id: String
        let status: ProductionStatus
    }
}