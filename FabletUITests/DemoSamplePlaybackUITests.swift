import XCTest

final class DemoSamplePlaybackUITests: XCTestCase {
    func testLocalSamplePlaysPausesAndSeeks() {
        let app = XCUIApplication()
        app.launch()
        app.tabBars.buttons["Library"].tap()
        let playSample = app.buttons["Play Locally narrated sample"]
        XCTAssertTrue(playSample.waitForExistence(timeout: 15))
        playSample.tap()

        let pause = app.buttons["Pause"]
        XCTAssertTrue(pause.waitForExistence(timeout: 15))
        let slider = app.sliders["Playback position"]
        XCTAssertTrue(slider.waitForExistence(timeout: 5))
        let advanced = NSPredicate { _, _ in
            guard let value = slider.value as? String else { return false }
            return !value.hasPrefix("0:00") && value.contains(" of ")
        }
        let progress = XCTNSPredicateExpectation(predicate: advanced, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [progress], timeout: 15), .completed)

        app.buttons["Forward 15 seconds"].tap()
        let seeked = NSPredicate { _, _ in
            guard let value = slider.value as? String,
                  let first = value.components(separatedBy: " of ").first else { return false }
            let parts = first.split(separator: ":").compactMap { Int($0) }
            return parts.count == 2 && parts[0] * 60 + parts[1] >= 15
        }
        let seek = XCTNSPredicateExpectation(predicate: seeked, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [seek], timeout: 10), .completed)
        pause.tap()
        XCTAssertTrue(app.buttons["Play"].waitForExistence(timeout: 5))
    }
}