import Foundation

enum AudiobookStyle: String, Codable, CaseIterable, Identifiable {
    case cinematicDocumentary = "cinematic_documentary"
    case calmExplainer = "calm_explainer"

    var id: String { rawValue }
    var title: String { self == .cinematicDocumentary ? "Cinematic Documentary" : "Calm Explainer" }
    var subtitle: String {
        self == .cinematicDocumentary
            ? "Immersive narration, atmospheric music, and dramatic storytelling."
            : "Thoughtful narration, gentle soundscapes, and clear explanations."
    }
}

enum ProductionStatus: String, Codable {
    case queued, researching, writing, narrating, scoring, mixing
    case qualityCheck = "quality_check"
    case completed, failed

    var label: String {
        switch self {
        case .queued: return "Queued"
        case .researching: return "Researching"
        case .writing: return "Writing"
        case .narrating: return "Narrating"
        case .scoring: return "Scoring"
        case .mixing: return "Mixing"
        case .qualityCheck: return "Quality check"
        case .completed: return "Completed"
        case .failed: return "Failed"
        }
    }

    var stageDescription: String {
        switch self {
        case .queued: return "In the production queue"
        case .completed: return "Ready to listen"
        case .failed: return "Production could not be completed"
        default: return label
        }
    }
}

struct Production: Codable, Identifiable {
    let id: String
    let status: ProductionStatus
    let progressPercent: Double
    let stageMessage: String
    let createdAt: String
    let updatedAt: String
    let prompt: String
    let durationMinutesRequested: Int
    let style: AudiobookStyle
    let title: String?
    let description: String?
    let durationSeconds: Double?
    let assetsAvailable: Bool
    let errorMessage: String?

    enum CodingKeys: String, CodingKey {
        case id, status, prompt, style, title, description
        case progressPercent = "progress_percent", stageMessage = "stage_message"
        case createdAt = "created_at", updatedAt = "updated_at"
        case durationMinutesRequested = "duration_minutes_requested"
        case durationSeconds = "duration_seconds", assetsAvailable = "assets_available"
        case errorMessage = "error_message"
    }

    func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(id, forKey: .id)
        try values.encode(status, forKey: .status)
        try values.encode(progressPercent, forKey: .progressPercent)
        try values.encode(stageMessage, forKey: .stageMessage)
        try values.encode(createdAt, forKey: .createdAt)
        try values.encode(updatedAt, forKey: .updatedAt)
        try values.encode(prompt, forKey: .prompt)
        try values.encode(durationMinutesRequested, forKey: .durationMinutesRequested)
        try values.encode(style, forKey: .style)
        try values.encode(title, forKey: .title)
        try values.encode(description, forKey: .description)
        try values.encode(durationSeconds, forKey: .durationSeconds)
        try values.encode(assetsAvailable, forKey: .assetsAvailable)
        try values.encode(errorMessage, forKey: .errorMessage)
    }
}

struct PlaybackURLs: Codable {
    let audioURL: URL
    let coverURL: URL
    let expiresAt: String

    enum CodingKeys: String, CodingKey {
        case audioURL = "audio_url", coverURL = "cover_url", expiresAt = "expires_at"
    }
}