import Combine
import Foundation

@MainActor
protocol ProductionRepository: AnyObject {
    func list() -> AnyPublisher<[Production], Error>
    func get(id: String) -> AnyPublisher<Production?, Error>
    func create(prompt: String, duration: Int, style: AudiobookStyle) async throws -> String
    func playbackURL(id: String) async throws -> PlaybackURLs
}

enum RepositoryError: LocalizedError {
    case invalidInput
    case playbackUnavailable
    case invalidResponse

    var errorDescription: String? {
        switch self {
        case .invalidInput: return "Enter a prompt of 10–2,000 characters and choose a supported length."
        case .playbackUnavailable: return "Playback is unavailable for this production."
        case .invalidResponse: return "The server returned an invalid production."
        }
    }
}

func validateProductionInput(prompt: String, duration: Int) throws -> String {
    let value = prompt.trimmingCharacters(in: .whitespacesAndNewlines)
    // JavaScript's string length counts UTF-16 code units.
    guard (10...2000).contains(value.utf16.count), [5, 10, 15].contains(duration) else {
        throw RepositoryError.invalidInput
    }
    return value
}