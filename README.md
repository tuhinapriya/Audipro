# Fablet iOS project

Open [Fablet.xcodeproj](Fablet.xcodeproj) in **Xcode 16 or later**, select the shared **Fablet** scheme, and choose an iOS 17+ iPhone simulator or a signed iPhone. Resolve packages when prompted, then use Product → Build or Product → Test. The app uses Swift 5 language mode (Xcode's `SWIFT_VERSION = 5.0`, including Swift 5.9 syntax); Xcode 16 is required for filesystem-synchronized groups and the Auth0 integration's Swift 6 package manifest. The Convex package itself requires Swift tools 5.10. No Xcode project generator is required.

The synchronized Fablet folder includes Swift files and resources recursively, including additions under App, Models, Services, and Features. The source Info plist is excluded from resource copying and processed by Xcode instead. Configuration templates at the root or under App are excluded from target membership to avoid colliding with the generated resources below; do not add other resources with those same names.

## Configuration and signing

In the **Fablet target → Build Settings**, set these user-defined settings separately for Debug and Release as needed:

| Build setting               | Meaning                                                                |
| --------------------------- | ---------------------------------------------------------------------- |
| `CONVEX_DEPLOYMENT_URL`     | HTTPS deployment URL. Leave blank for the local demo repository.       |
| `AUTH0_DOMAIN`              | Auth0 tenant domain, without scheme, for live mode.                    |
| `AUTH0_CLIENT_ID`           | Auth0 native application client ID, for live mode.                     |
| `PRODUCT_BUNDLE_IDENTIFIER` | Replace the example identifier with your own, especially for a device. |
| `DEVELOPMENT_TEAM`          | Select your signing team in Signing & Capabilities for device builds.  |

Use Xcode's build settings editor for URLs (an xcconfig file interprets `//` as a comment unless escaped). The processed Info plist contains these public configuration values. A build phase reads it and writes the bundled configuration resources expected by the current app: `FABLET_CONVEX_URL` in FabletConfig and `Domain`/`ClientId` in Auth0. Empty deployment selects demo mode; a nonempty valid HTTPS URL plus Auth0 values selects live mode. Configure the matching native application and callback/logout URLs in Auth0 and its identity provider in Convex. The app URL scheme is its bundle identifier; changing it requires updating the registered Auth0 URLs. Never put worker API keys, storage credentials, client secrets, or other secrets in build settings or the app bundle.

Dependencies are pinned to ConvexMobile 0.8.2, ConvexAuth0 0.4.0, and Auth0 2.17.0. ConvexAuth0 0.4.0 declares Convex 0.8.x and Auth0 2.17.0. The Convex binary at 0.8.2 includes an **arm64 iOS simulator** slice and an arm64 device slice, but no x86_64 simulator slice; use Apple silicon for simulator builds.

## Tests and limits

The shared scheme includes hosted XCTest and XCUITest targets. Tests cover input boundaries, UTF-16 length, model wire decoding and presentation fallbacks, plus navigation, form validation and a demo creation flow. UI tests require the Debug deployment URL to be blank, so they run in demo mode without signing in or sending jobs to a real backend. The creation test saves a queued item in the app's local demo store; it does not clean up existing local data. Use a dedicated simulator or delete the app afterward for isolation. Demo mode does not process jobs or provide playable media.

For a command-line test on a Mac with full Xcode installed, choose an available iPhone simulator name and run:

```sh
xcodebuild -project Fablet.xcodeproj -scheme Fablet -destination 'platform=iOS Simulator,name=iPhone 16' test
```

The simulator can exercise interface and repository behavior but cannot establish real background playback, lock-screen controls, audio interruptions, routing, or behavior under device lock. Verify those on a signed physical iPhone with a real completed production and valid playback URLs. Live authentication, backend authorization, worker processing, expiring URL refresh, and actual audio delivery require separately configured services and are not covered by these demo tests. The form and backend both count UTF-16 code units for prompt validation.

This project was assembled without full Xcode; package resolution, compilation, signing, and tests have not been verified here.
