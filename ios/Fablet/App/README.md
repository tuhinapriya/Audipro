# Native app integration

The included Xcode project targets iOS 17 and uses filesystem-synchronized groups. See the project README for the exact build settings. The default empty deployment URL selects the persistent, local-only Demo; jobs stay queued and cannot play. The build generates the bundled configuration resources from the target's build settings. A missing configuration file is an error, not an implicit demo fallback.

## Packages

Add `https://github.com/convex/convex-swift-auth0` with Swift Package Manager and link its `ConvexAuth0` product, plus `ConvexMobile` from `https://github.com/convex/convex-swift` and `Auth0` from `https://github.com/auth0/Auth0.swift` to the app target. Resolve compatible versions together: the current auth integration's package manifest requires Convex Swift `0.8.x` and Auth0.swift exactly `2.17.0`; do not independently upgrade Auth0 to 3.x. The current integration requires Swift 6 tooling. Verify resolved versions against the selected auth integration release before shipping.

## Live configuration and Auth0

1. Set `CONVEX_DEPLOYMENT_URL` in the target's build settings to the HTTPS Convex **client** deployment URL (`.convex.cloud`, not the worker `.convex.site` URL). A nonempty invalid value fails closed; it never switches to demo.
2. Create an Auth0 **Native** application. Set `AUTH0_DOMAIN` (hostname only, without `https://`) and `AUTH0_CLIENT_ID` in the target's build settings. The build generates the corresponding bundled configuration. These are public application configuration, not a client secret. Do not put Auth0 client secrets, worker keys, R2 credentials, JWTs, or signed URLs in the bundle.
3. Register the bundle identifier as a custom URL scheme in the app target's URL Types. In Auth0's Allowed Callback URLs and Allowed Logout URLs, add `BUNDLE_ID://AUTH0_DOMAIN/ios/BUNDLE_ID/callback`, substituting the exact bundle ID and domain. The integration's `Auth0Provider` uses the SDK's default custom-scheme flow, not `.useHTTPS()`. Configure refresh-token/`offline_access` support for persistent sessions. Review Auth0's native application security guidance and test callback handling on a device.
4. Set the backend's `AUTH_ISSUER` to the exact HTTPS Auth0 OIDC issuer (including its required trailing slash) and `AUTH_AUDIENCE` to the native application's client ID, matching the ID token's `iss` and `aud`. Push the backend auth configuration to the same deployment. The provider sends the Auth0 **ID token**, not a user-provided identity or an API access token. See the backend README for deployment and R2 setup.
5. The supplied target declares the audio background mode and includes separate XCTest and XCUITest targets. Select your signing team for a physical device.

Live list and detail use separate Convex subscriptions; detail is not limited to the list's 20 most recent results. Refresh and foregrounding re-subscribe. A null detail means missing or unauthorized; a query failure produces a separate error banner. No fake progress is introduced. The player clears signed URLs and private metadata if authentication ends; account switching UI is not implemented.

The SDK integration, Auth0 callback/refresh, backend subscriptions, R2 signed URLs, player background behavior, and device playback need a full Xcode build and a configured deployment/device test. `swiftc -frontend -parse` alone cannot check linked SDKs or SwiftUI types.
