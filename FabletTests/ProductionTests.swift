import Foundation
import XCTest
@testable import Fablet

final class ProductionTests: XCTestCase {
    func testPromptValidationTrimsAndAcceptsBoundariesAndDurations() throws {
        XCTAssertEqual(try validateProductionInput(prompt: "  1234567890\n", duration: 5), "1234567890")
        XCTAssertEqual(try validateProductionInput(prompt: String(repeating: "a", count: 2000), duration: 15).count, 2000)
        XCTAssertNoThrow(try validateProductionInput(prompt: "1234567890", duration: 10))
    }

    func testPromptValidationRejectsInvalidLengthsAndDurations() {
        for prompt in ["", "  123456789  ", String(repeating: "a", count: 2001)] {
            XCTAssertThrowsError(try validateProductionInput(prompt: prompt, duration: 10))
        }
        for duration: Double in [0, -1] {
            XCTAssertThrowsError(try validateProductionInput(prompt: "1234567890", duration: duration))
        }
    }

    func testRequestedDurationDefaultsAndReadsPrompt() throws {
        XCTAssertEqual(try requestedDuration(in: "Tell me about the ocean"), 1)
        XCTAssertEqual(try requestedDuration(in: "Make a 3-minute story about space"), 3)
        XCTAssertEqual(try requestedDuration(in: "Tell me about space in five minutes"), 5)
        XCTAssertEqual(try requestedDuration(in: "Make a 20 minute story"), 20)
        XCTAssertEqual(try requestedDuration(in: "Make a 1.5 minute story"), 1.5)
        XCTAssertEqual(try requestedDuration(in: "Make a 30-second story"), 0.5)
        XCTAssertThrowsError(try requestedDuration(in: "Make a 2 minute or 3 minute story"))
    }

    func testPromptValidationUsesBackendUTF16Length() {
        XCTAssertNoThrow(try validateProductionInput(prompt: String(repeating: "😀", count: 5), duration: 10))
        XCTAssertThrowsError(try validateProductionInput(prompt: String(repeating: "😀", count: 1001), duration: 10))
    }

    func testProductionDecodesBackendKeysAndStatus() throws {
        let json = """
        {"id":"prod_123","status":"quality_check","progress_percent":92,
         "stage_message":"Checking audio","created_at":"2026-11-15T00:00:00Z",
         "updated_at":"2026-11-15T00:00:00Z","prompt":"A story about the ocean",
         "duration_minutes_requested":10,"style":"calm_explainer","title":null,
         "description":null,"duration_seconds":null,"assets_available":false,"error_message":null}
        """
        let production = try JSONDecoder().decode(Production.self, from: Data(json.utf8))
        XCTAssertEqual(production.id, "prod_123")
        XCTAssertEqual(production.status, .qualityCheck)
        XCTAssertEqual(production.progressPercent, 92)
        XCTAssertEqual(production.durationMinutesRequested, 10)
        XCTAssertEqual(production.style, .calmExplainer)
        XCTAssertFalse(production.assetsAvailable)
        XCTAssertNil(production.title)
        XCTAssertEqual(try JSONDecoder().decode(Production.self, from: JSONEncoder().encode(production)).status, .qualityCheck)
    }

    func testStatusAndStyleWireValues() throws {
        let statuses: [ProductionStatus] = [.queued, .researching, .writing, .narrating, .scoring, .mixing, .qualityCheck, .completed, .failed]
        XCTAssertEqual(statuses.map(\.rawValue), ["queued", "researching", "writing", "narrating", "scoring", "mixing", "quality_check", "completed", "failed"])
        XCTAssertTrue(statuses.allSatisfy { !$0.label.isEmpty && !$0.stageDescription.isEmpty })
        XCTAssertEqual(Set(AudiobookStyle.allCases.map(\.rawValue)), Set(["cinematic_scene", "cinematic_documentary", "calm_explainer"]))
        XCTAssertThrowsError(try JSONDecoder().decode(ProductionStatus.self, from: Data("\"unknown\"".utf8)))
    }

    func testPlaybackURLKeysDecode() throws {
        let json = """
        {"audio_url":"https://example.com/audio.mp3","cover_url":"https://example.com/cover.jpg","expires_at":"2026-11-15T00:00:00Z"}
        """
        let urls = try JSONDecoder().decode(PlaybackURLs.self, from: Data(json.utf8))
        XCTAssertEqual(urls.audioURL.host, "example.com")
        XCTAssertEqual(urls.coverURL.lastPathComponent, "cover.jpg")
        XCTAssertEqual(urls.expiresAt, "2026-11-15T00:00:00Z")
    }

    func testProductionPresentationFallbacks() {
        let production = Production(id: "p1", status: .queued, progressPercent: 0,
            stageMessage: "  ", createdAt: "", updatedAt: "", prompt: "  Deep oceans  ",
            durationMinutesRequested: 10, style: .cinematicDocumentary, title: "  ",
            description: nil, durationSeconds: nil, assetsAvailable: false, errorMessage: nil)
        XCTAssertEqual(fabletProductionTitle(production), "Deep oceans")
        XCTAssertEqual(fabletStageMessage(production), "In the production queue")
        XCTAssertEqual(fabletDuration(production), "10:00")
    }
}