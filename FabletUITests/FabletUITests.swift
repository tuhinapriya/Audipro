import XCTest

final class FabletUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testHomeLibraryAndCreateNavigation() {
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.buttons["Create a Story"].waitForExistence(timeout: 15), "Run these tests in demo mode.")
        app.buttons["Create a Story"].tap()
        XCTAssertTrue(app.textViews["What are you curious about?"].waitForExistence(timeout: 5))
        app.tabBars.buttons["Library"].tap()
        XCTAssertTrue(app.staticTexts["Your Library"].waitForExistence(timeout: 5))
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
        app.swipeUp()
        XCTAssertTrue(submit.waitForExistence(timeout: 5))
        XCTAssertFalse(submit.isEnabled)
        prompt.tap()
        prompt.typeText("0")
        app.swipeUp()
        XCTAssertTrue(submit.isEnabled)
        submit.tap()
        XCTAssertTrue(app.staticTexts["In the production queue"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["Demo only — saved locally; no production worker is running."].waitForExistence(timeout: 5))
    }
}