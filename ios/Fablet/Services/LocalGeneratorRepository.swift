import Combine
import Foundation

/// Simulator-only bridge to the generator running on this Mac.
@MainActor
final class LocalGeneratorRepository: ProductionRepository {
    private let base = URL(string: "http://127.0.0.1:8766/productions")!

    func list() -> AnyPublisher<[Production], Error> {
        poll(base, as: [Production].self)
    }
    func get(id: String) -> AnyPublisher<Production?, Error> {
        poll(base.appendingPathComponent(id), as: Production.self).map(Optional.some).eraseToAnyPublisher()
    }
    private func poll<T: Decodable>(_ url: URL, as: T.Type) -> AnyPublisher<T, Error> {
        Timer.publish(every: 2, on: .main, in: .common).autoconnect().prepend(Date())
            .flatMap { _ in URLSession.shared.dataTaskPublisher(for: url)
                .tryMap { data, response in
                    guard let response = response as? HTTPURLResponse, (200...299).contains(response.statusCode) else { throw RepositoryError.invalidResponse }
                    return try JSONDecoder().decode(T.self, from: data)
                }
            }.eraseToAnyPublisher()
    }
    func create(prompt: String, duration: Double, style: AudiobookStyle) async throws -> String {
        let prompt = try validateProductionInput(prompt: prompt, duration: duration)
        var request = URLRequest(url: base)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["prompt": prompt, "duration": duration, "style": style.rawValue])
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let response = response as? HTTPURLResponse, response.statusCode == 201,
              let object = try JSONSerialization.jsonObject(with: data) as? [String: String], let id = object["id"] else { throw RepositoryError.invalidResponse }
        return id
    }
    func playbackURL(id: String) async throws -> PlaybackURLs {
        let (data, response) = try await URLSession.shared.data(from: base.appendingPathComponent(id).appendingPathComponent("playback"))
        guard let response = response as? HTTPURLResponse, response.statusCode == 200 else { throw RepositoryError.playbackUnavailable }
        return try JSONDecoder().decode(PlaybackURLs.self, from: data)
    }
}
