import XCTest

final class FabletUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    func testHomeLibraryAndCreateNavigation() {
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.buttons["Create a Story"].waitForExistence(timeout: 15), "Run these tests in demo mode.")
        capture("Home")
        app.buttons["Create a Story"].tap()
        XCTAssertTrue(app.textViews["What are you curious about?"].waitForExistence(timeout: 5))
        capture("Create")
        app.tabBars.buttons["Library"].tap()
        XCTAssertTrue(app.staticTexts["Your Library"].waitForExistence(timeout: 5))
        capture("Library")
        app.tabBars.buttons["Home"].tap()
        XCTAssertTrue(app.buttons["Create a Story"].waitForExistence(timeout: 5))
    }

    func testPromptValidationAndDemoCreation() {
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.buttons["Create a Story"].waitForExistence(timeout: 15), "Run these tests in demo mode.")
        app.buttons["Create a Story"].tap()
        let prompt = app.textViews["What are you curious about?"]
        XCTAssertTrue(prompt.waitForExistence(timeout: 5))
        prompt.tap()
        prompt.typeText("123456789")
        let submit = app.buttons["Create my audiobook"]
        XCTAssertTrue(submit.waitForExistence(timeout: 5))
        XCTAssertFalse(submit.isEnabled)
        prompt.typeText("0")
        XCTAssertTrue(submit.isEnabled)
        for _ in 0..<5 where !submit.isHittable { app.swipeUp() }
        XCTAssertTrue(submit.isHittable)
        submit.tap()
        XCTAssertTrue(app.staticTexts["In the production queue"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["Demo only — saved locally; no production worker is running."].waitForExistence(timeout: 5))
        capture("Production Details")
        app.tabBars.buttons["Library"].tap()
        XCTAssertTrue(app.staticTexts["1234567890"].firstMatch.waitForExistence(timeout: 5))
        app.terminate()
        app.launch()
        app.tabBars.buttons["Library"].tap()
        XCTAssertTrue(app.staticTexts["1234567890"].firstMatch.waitForExistence(timeout: 5))
    }
}