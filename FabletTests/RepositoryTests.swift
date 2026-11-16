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
        XCTAssertThrowsError(try validateProductionInput(prompt: "A long enough prompt", duration: 0))
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