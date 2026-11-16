import Combine
import Foundation
import XCTest
@testable import Fablet

@MainActor
final class RepositoryTests: XCTestCase {
    func testDemoPersistsOnlyQueuedProductionsAndCannotPlay() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let file = directory.appendingPathComponent("demo.json")
        let repository = DemoProductionRepository(fileURL: file)
        let id = try await repository.create(prompt: "  A very curious story  ", duration: 10, style: .calmExplainer)
        let reloaded = DemoProductionRepository(fileURL: file)
        let production = try await reloaded.get(id: id).values.first { _ in true }
        XCTAssertEqual(production??.id, id)
        XCTAssertEqual(production??.prompt, "A very curious story")
        XCTAssertEqual(production??.status, .queued)
        XCTAssertEqual(production??.progressPercent, 0)
        XCTAssertEqual(production??.assetsAvailable, false)
        do {
            _ = try await reloaded.playbackURL(id: id)
            XCTFail("Demo playback must not be available")
        } catch { }
    }

    func testDemoRejectsMissingOrInvalidSampleFiles() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let audio = directory.appendingPathComponent("local-sample.mp3")
        let cover = directory.appendingPathComponent("local-sample.png")
        try Data("not audio".utf8).write(to: audio)
        try Data("cover".utf8).write(to: cover)
        for repository in [
            DemoProductionRepository(fileURL: directory.appendingPathComponent("missing.json"), sampleAudioURL: audio, sampleCoverURL: nil),
            DemoProductionRepository(fileURL: directory.appendingPathComponent("missing-audio.json"), sampleAudioURL: nil, sampleCoverURL: cover),
            DemoProductionRepository(fileURL: directory.appendingPathComponent("invalid.json"), sampleAudioURL: audio, sampleCoverURL: cover)
        ] {
            let records = try await repository.list().values.first { _ in true }
            XCTAssertEqual(records?.count, 0)
            do {
                _ = try await repository.playbackURL(id: DemoProductionRepository.sampleID)
                XCTFail("Invalid sample must not be playable")
            } catch { }
        }
    }

    func testBundledSampleIsPlayableAndNeverPersisted() async throws {
        guard DemoProductionRepository.bundledResource("local-sample", extension: "mp3") != nil,
              DemoProductionRepository.bundledResource("local-sample", extension: "png") != nil else {
            throw XCTSkip("Bundled sample assets are not available")
        }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let file = directory.appendingPathComponent("demo.json")
        let repository = DemoProductionRepository(fileURL: file)
        let sample = try await repository.get(id: DemoProductionRepository.sampleID).values.first { _ in true }
        XCTAssertEqual(sample??.title, "Locally narrated sample")
        XCTAssertEqual(sample??.status, .completed)
        XCTAssertEqual(sample??.assetsAvailable, true)
        XCTAssertEqual(sample??.description, "Pre-rendered locally with macOS narration; not a Convex production.")
        XCTAssertGreaterThan(sample??.durationSeconds ?? 0, 0)
        let urls = try await repository.playbackURL(id: DemoProductionRepository.sampleID)
        XCTAssertTrue(urls.audioURL.isFileURL)
        XCTAssertTrue(urls.coverURL.isFileURL)
        XCTAssertEqual(urls.expiresAt, "")
        _ = try await repository.create(prompt: "A very curious story", duration: 10, style: .calmExplainer)
        let persisted = try JSONDecoder().decode([Production].self, from: Data(contentsOf: file))
        XCTAssertEqual(persisted.count, 1)
        XCTAssertEqual(persisted.first?.status, .queued)
        XCTAssertFalse(persisted.contains { $0.id == DemoProductionRepository.sampleID })
        let reloaded = DemoProductionRepository(fileURL: file)
        let records = try await reloaded.list().values.first { _ in true }
        XCTAssertEqual(records?.count, 2)
        XCTAssertEqual(records?.filter { $0.id == DemoProductionRepository.sampleID }.count, 1)
    }

    func testWireKeysAndInputValidation() throws {
        let json = """
        {"id":"p1","status":"queued","progress_percent":0,"stage_message":"Queued",
        "created_at":"2026-11-15T00:00:00Z","updated_at":"2026-11-15T00:00:00Z",
        "prompt":"A long prompt","duration_minutes_requested":10,"style":"cinematic_documentary",
        "title":null,"description":null,"duration_seconds":null,"assets_available":false,"error_message":null}
        """
        let production = try JSONDecoder().decode(Production.self, from: Data(json.utf8))
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(production)) as? [String: Any])
        XCTAssertEqual(object["duration_minutes_requested"] as? Int, 10)
        XCTAssertEqual(object["progress_percent"] as? Double, 0)
        XCTAssertTrue(object["duration_seconds"] is NSNull)
        XCTAssertThrowsError(try validateProductionInput(prompt: "short", duration: 10))
        XCTAssertThrowsError(try validateProductionInput(prompt: "A long enough prompt", duration: 7))
    }

    func testConvexFloatWireDecoding() throws {
        let json = """
        {"id":"p1","status":"queued","progress_percent":{"$float":"AAAAAAAAJEA="},
        "stage_message":"Queued","created_at":"2026-11-15T00:00:00Z",
        "updated_at":"2026-11-15T00:00:00Z","prompt":"A long prompt",
        "duration_minutes_requested":10,"style":"cinematic_documentary","title":null,
        "description":null,"duration_seconds":null,"assets_available":false,"error_message":null}
        """
        let wire = try JSONDecoder().decode(ConvexProduction.self, from: Data(json.utf8))
        let production = try wire.model()
        XCTAssertEqual(production.progressPercent, 10)
        XCTAssertEqual(production.durationMinutesRequested, 10)
        XCTAssertNil(production.durationSeconds)
    }
}