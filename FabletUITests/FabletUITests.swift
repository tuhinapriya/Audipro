import XCTest

final class FabletUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    func testHomeAndLibraryNavigation() {
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.textViews["Describe what you want to hear"].waitForExistence(timeout: 15))
        XCTAssertTrue(app.staticTexts["Recents"].exists)
        XCTAssertFalse(app.tabBars.buttons["Create"].exists)
        app.tabBars.buttons["Library"].tap()
        XCTAssertTrue(app.staticTexts["Your Library"].waitForExistence(timeout: 5))
        app.tabBars.buttons["Home"].tap()
        XCTAssertTrue(app.textViews["Describe what you want to hear"].waitForExistence(timeout: 5))
    }

    func testPromptCreatesProduction() {
        let app = XCUIApplication()
        app.launch()
        let prompt = app.textViews["Describe what you want to hear"]
        XCTAssertTrue(prompt.waitForExistence(timeout: 15))
        let submit = app.buttons["Create audio"]
        XCTAssertFalse(submit.isEnabled)
        prompt.tap()
        prompt.typeText("Tell me about the ocean in 3 minutes")
        XCTAssertTrue(submit.isEnabled)
        submit.tap()
        XCTAssertTrue(app.staticTexts["In the production queue"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["Demo only — saved locally; no production worker is running."].waitForExistence(timeout: 5))
    }
}
