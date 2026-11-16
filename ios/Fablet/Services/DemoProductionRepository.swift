import Combine
import Foundation

/// A separate local store, deliberately without a worker or simulated progression.
@MainActor
final class DemoProductionRepository: ProductionRepository {
    private let subject: CurrentValueSubject<[Production], Error>
    private let fileURL: URL
    private var loadError: Error?

    init(fileURL: URL? = nil) {
        let directory = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Fablet", isDirectory: true)
        self.fileURL = fileURL ?? directory.appendingPathComponent("demo-productions.json")
        var records: [Production] = []
        if FileManager.default.fileExists(atPath: self.fileURL.path) {
            do {
                records = try JSONDecoder().decode([Production].self, from: Data(contentsOf: self.fileURL))
                guard records.allSatisfy({ $0.status == .queued && $0.progressPercent == 0 && !$0.assetsAvailable }) else {
                    throw DemoStoreError.unavailable
                }
            }
            catch { loadError = error }
        }
        subject = CurrentValueSubject(records)
    }

    func list() -> AnyPublisher<[Production], Error> {
        if loadError != nil { return Fail(error: DemoStoreError.unavailable).eraseToAnyPublisher() }
        return subject.eraseToAnyPublisher()
    }

    func get(id: String) -> AnyPublisher<Production?, Error> {
        if loadError != nil { return Fail(error: DemoStoreError.unavailable).eraseToAnyPublisher() }
        return subject.map { $0.first { $0.id == id } }.eraseToAnyPublisher()
    }

    func create(prompt: String, duration: Double, style: AudiobookStyle) async throws -> String {
        guard loadError == nil else { throw DemoStoreError.unavailable }
        let prompt = try validateProductionInput(prompt: prompt, duration: duration)
        let now = ISO8601DateFormatter().string(from: Date())
        let production = Production(id: UUID().uuidString, status: .queued, progressPercent: 0,
            stageMessage: "Demo only — saved locally; no production worker is running.",
            createdAt: now, updatedAt: now, prompt: prompt, durationMinutesRequested: duration,
            style: style, title: nil, description: nil, durationSeconds: nil,
            assetsAvailable: false, errorMessage: nil)
        let records = [production] + subject.value
        do {
            try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try JSONEncoder().encode(records).write(to: fileURL, options: [.atomic, .completeFileProtectionUnlessOpen])
        } catch { throw DemoStoreError.unavailable }
        subject.send(records)
        return production.id
    }

    func playbackURL(id: String) async throws -> PlaybackURLs { throw RepositoryError.playbackUnavailable }

    private enum DemoStoreError: LocalizedError {
        case unavailable
        var errorDescription: String? { "The local demo library could not be read or saved." }
    }
}