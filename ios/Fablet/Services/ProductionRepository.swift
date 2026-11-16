import Combine
import Foundation

@MainActor
protocol ProductionRepository: AnyObject {
    func list() -> AnyPublisher<[Production], Error>
    func get(id: String) -> AnyPublisher<Production?, Error>
    func create(prompt: String, duration: Double, style: AudiobookStyle) async throws -> String
    func playbackURL(id: String) async throws -> PlaybackURLs
}

enum RepositoryError: LocalizedError {
    case invalidInput
    case playbackUnavailable
    case invalidResponse
    case sceneUnavailable
    case invalidDuration

    var errorDescription: String? {
        switch self {
        case .invalidInput: return "Enter a prompt of 10–2,000 characters and request at least 10 seconds."
        case .playbackUnavailable: return "Playback is unavailable for this production."
        case .invalidResponse: return "The server returned an invalid production."
        case .sceneUnavailable: return "Cinematic scenes are currently available in the local demo only."
        case .invalidDuration: return "Please request one length of at least 10 seconds."
        }
    }
}

func validateProductionInput(prompt: String, duration: Double) throws -> String {
    let value = prompt.trimmingCharacters(in: .whitespacesAndNewlines)
    // JavaScript's string length counts UTF-16 code units.
    guard (10...2000).contains(value.utf16.count), duration.isFinite, duration >= 1.0 / 6.0 else {
        throw RepositoryError.invalidInput
    }
    return value
}
/// Interpret explicit seconds or minutes; default to one minute.
func requestedDuration(in prompt: String) throws -> Double {
    let words: [String: Double] = ["one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "sixty": 60]
    let pattern = #"(?i)\b(\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|twenty|thirty|forty|sixty)[ -]+(minutes?|mins?|seconds?|secs?|hours?|hrs?)\b"#
    let regex = try NSRegularExpression(pattern: pattern)
    let matches = regex.matches(in: prompt, range: NSRange(prompt.startIndex..., in: prompt))
    guard let match = matches.first else { return 1 }
    guard matches.count == 1, let valueRange = Range(match.range(at: 1), in: prompt), let unitRange = Range(match.range(at: 2), in: prompt) else { throw RepositoryError.invalidDuration }
    let value = String(prompt[valueRange]).lowercased()
    let unit = prompt[unitRange].lowercased()
    guard let amount = Double(value) ?? words[value] else { throw RepositoryError.invalidDuration }
    let minutes = unit.hasPrefix("s") ? amount / 60 : (unit.hasPrefix("h") ? amount * 60 : amount)
    guard minutes.isFinite, minutes >= 1.0 / 6.0 else { throw RepositoryError.invalidDuration }
    return minutes
}
