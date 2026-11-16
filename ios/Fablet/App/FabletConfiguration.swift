import Foundation

enum FabletConfiguration {
    case demo
    case live(String)
    case invalid(String)

    static func load(bundle: Bundle = .main) -> Self {
        guard let url = bundle.url(forResource: "FabletConfig", withExtension: "plist"),
              let data = try? Data(contentsOf: url),
              let values = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any],
              let raw = values["FABLET_CONVEX_URL"] as? String else {
            return .invalid("FabletConfig.plist is missing or invalid. Add it to the app bundle.")
        }
        let deployment = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if deployment.isEmpty { return .demo }
        guard let components = URLComponents(string: deployment), components.scheme == "https",
              components.host != nil, components.user == nil, components.password == nil,
              components.query == nil, components.fragment == nil else {
            return .invalid("The Convex deployment URL must be a valid HTTPS URL.")
        }
        guard let authURL = bundle.url(forResource: "Auth0", withExtension: "plist"),
              let authData = try? Data(contentsOf: authURL),
              let auth = try? PropertyListSerialization.propertyList(from: authData, format: nil) as? [String: Any],
              let domain = auth["Domain"] as? String, !domain.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              let clientID = auth["ClientId"] as? String, !clientID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return .invalid("Live mode requires a bundled Auth0.plist with Domain and ClientId.")
        }
                guard domain == domain.trimmingCharacters(in: .whitespacesAndNewlines),
                            let domainURL = URLComponents(string: "https://\(domain)"),
                            domainURL.host == domain, domainURL.port == nil, domainURL.path.isEmpty,
                            domainURL.user == nil, domainURL.password == nil, domainURL.query == nil,
                            domainURL.fragment == nil else {
                        return .invalid("The Auth0 domain must be a hostname without a scheme or path.")
                }
        return .live(deployment)
    }
}