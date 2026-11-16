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

---

# Fablet production engine

Python worker and local CLI for the Fablet iOS audiobook app. The worker calls the teammate's Convex HTTP endpoints; it does not implement the production backend. Real providers have not yet been validated end to end.

## Setup

Python 3.12+, FFmpeg and ffprobe are required. On macOS: `brew install ffmpeg`. On Debian/Ubuntu: `sudo apt-get install ffmpeg`. Create a virtual environment, then `pip install -e '.[test]'`. Copy `.env.example` to `.env`; set `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_IMAGE_MODEL`, `ELEVENLABS_API_KEY`, and `ELEVENLABS_VOICE_ID`. Choose accessible models and voice IDs and check account terms, quotas and cost before generation. ElevenLabs Music requires an eligible plan. No credentials are needed for the local test suite.

```
python -m fablet generate --prompt 'The Fermi Paradox, told as a cinematic mystery' --duration 5 --style cinematic_documentary --output ./outputs/fermi --smoke
python -m fablet.mock_api --port 8765
python -m fablet worker --output ./outputs/worker
pytest -q
```

`--smoke` targets around 75 seconds; actual length varies. Remove it for a 5, 10 or 15 minute target. The worker additionally needs `WORKER_BASE_URL`, `WORKER_API_KEY`, `R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, and `R2_BUCKET`. `WORKER_BASE_URL` must include `/worker`. SIGINT or SIGTERM stops polling and abandons the active job at the next stage boundary; a provider call already in flight cannot be interrupted. Production exceptions report a safe failure when the lease is still accepted; an unconfirmed lease fails closed. The worker preserves closed attempt artifacts locally and copies them into the next local attempt for content-hash checked reuse; do not run multiple workers with the same work directory.

## Shared contract amendment — teammate action required

This change supersedes the shared final keys in v2 and **must be implemented in Convex before using the worker against it**:

1. Each successful claim atomically generates and persists a fresh unique path-safe `attempt_id` (`[A-Za-z0-9_-]{1,128}`), returns it alongside `job`, `lease_token` and `lease_expires_at`, and associates it with the new lease. Never reuse it.
2. The worker conditionally creates `productions/{job_id}/{attempt_id}/master.mp3` and `productions/{job_id}/{attempt_id}/cover.webp`, then includes `attempt_id` and those exact object keys in the existing completion `manifest` alongside title, description, duration and `mime_type`. It verifies the upload sizes. The storage service must support conditional `If-None-Match: *` writes.
3. In the same atomic transaction that stores the manifest and marks the job completed, Convex must check the job's current attempt ID and lease token, verify that the lease is unexpired and the job is not terminal, and reject mismatches with HTTP 409. Validate exact keys and, where possible, check objects exist. Identical completion retries using the accepted lease and manifest may return success; stale attempts may never replace them.
4. Playback uses the keys from the accepted manifest. No worker promotes objects to shared mutable keys. Orphaned attempt objects may be cleaned up separately after an appropriate retention period.

The local mock is an in-memory, localhost-only test service, not a substitute for Convex. All endpoints require its bearer key (default `local-test-key`). It adds local-only `POST /worker/create`, `/worker/get`, and `/worker/retry` for testing. State disappears when it stops.

## Quality and limitations

The renderer places stems deterministically, overlaps and fades repeated music, ducks music using the narration sidechain, and normalizes loudness. QA checks valid audio and cover, output duration, peak level and long silence. It does not perform transcription or forced alignment, verify factual entailment, or guarantee artistic quality. Listen through every production and inspect research and the QA report before use. Generated speech is not known to match its text merely because a segment exists. The provider adapters, R2 conditional write behavior, native client compatibility, and real production quality still require live integration tests. Full generated durations are targets, not guaranteed. Existing account and provider settings may affect API access and output.

## First real production setup and audit

The API key is created in the [OpenAI API dashboard](https://platform.openai.com/api-keys); an ElevenLabs API key is created in the [ElevenLabs dashboard](https://elevenlabs.io/app/settings/api-keys). Store them in the local `.env`, never in a commit or chat. The sample configuration uses `gpt-4.1`, `gpt-image-2`, `eleven_multilingual_v2`, `music_v1`, `eleven_text_to_sound_v2`, and `whisper-1`; verify your accounts can access each. Install dependencies and copy the configuration with:

```
cp .env.example .env
# Edit .env locally; set OPENAI_API_KEY and ELEVENLABS_API_KEY.
python -m fablet voices
# Put a voice_id from that list in ELEVENLABS_VOICE_ID.
python -m fablet generate --prompt "The Fermi Paradox: Why Haven't We Found Anyone?" --duration 5 --smoke --style cinematic_documentary --output ./outputs/fermi
python -m fablet transcribe --output ./outputs/fermi
```

The model defaults are examples, not guarantees of account entitlement. The ElevenLabs voice listing prints the first page of voices; use the dashboard for additional voices. Music API requires an eligible paid subscription, and image generation may require organization verification. Provider calls incur charges; consult each account's current pricing and usage dashboard. The transcription command makes additional paid OpenAI requests and compares each narration stem independently; it flags differences, which may be transcription errors. The pipeline keeps `provider_usage.jsonl` with available OpenAI usage metadata and ElevenLabs requested character/duration counts; it cannot infer authoritative costs or billing for cached calls, failed/time-out requests, or provider-side retries. Check provider billing dashboards for actual charges.

The adapters follow the documented OpenAI Responses web-search and structured-output interfaces and Images API, and ElevenLabs text-to-speech, music and sound-generation REST endpoints. Citations and research response are retained; URLs are checked against the web-search source list, but factual entailment is not automatically guaranteed. Model responses can omit SFX, so review `direction.json` before judging sound design. This has not yet been tested against real provider accounts. A successful render and transcript are evidence only: check the script's sources, listen to the entire result, assess pronunciation, voice consistency and music balance, and regenerate defective stem files by removing their corresponding `.sha256` sidecars before rerunning. Re-run transcription after a changed stem.

## Direction experiments and comparison renders

`python -m fablet.compare outputs/fermi` renders non-destructive `master_basic.mp3`, `master_ducked.mp3`, and `master_directed.mp3` from cached stems, with cue sheets and QA reports. It applies active-level calibration and configurable FFmpeg loudness normalization; equal-power-style fades reduce hard edges. Compare these by ear before treating the settings as a production standard.

`python -m fablet.alignment OUTPUT_DIR` uses paid OpenAI Whisper word transcription; it saves cached word timestamps as evidence, not ground truth. `python -m fablet.direct_production OUTPUT_DIR` requests a structured audio direction plan, resolves segment and aligned phrase anchors against existing stems, renders `master_directed.mp3`, and records unresolved cues. The script uses existing assets and does not synthesize missing cues. Its current implementation uses short planned score-gain ramps and fades; silence requests are flagged for manual review, and J-cuts/L-cuts are not yet scheduled as distinct transition algorithms. It does not guarantee musical crossfades, uninterrupted ambience, perceptual speech/music separation, or artistic quality. Manually edited plans require retaining the original plan and reviewing cue sheet/QA output. Never interpret a successful loudness check as proof that the mix is good.

## Character dialogue scenes

`python -m fablet.cinematic --plan PLAN.json --output OUTPUT_DIR --cover COVER.webp` renders a short fictionalized scene from a validated `NarrativeDirectionPlan`. Cast voice IDs must be available to the configured ElevenLabs account. Each character turn may have an inline v4 delivery instruction, such as `whispers` or `urgent`, and optional `pause_after_seconds`. The ElevenLabs Text to Dialogue API generates one conversational performance with separate speakers; the full performance, provider timing metadata, and timestamp-derived turn clips are retained. Nonzero requested turn pauses use the aligned clips, so missing timestamps cause a clear error rather than guessed timing. Scene actions can anchor to a particular dialogue turn. Narrator, dialogue, music, ambience, and effects remain separate source assets.

The demo plan is stored with its output under `outputs/rome_dialogue/`. Generation incurs provider charges. As with the documentary pipeline, timing and transcription are evidence rather than a guarantee of acting quality or intelligibility; review the complete mixed scene by ear. Music gain ramps and ambience loops are basic; elaborate dramatic transitions remain a work in progress.

## Blueprint-driven scene director

`fablet.scene_director` provides `SceneBlueprint`, `VoiceProfile`, ordered `DramaticEvent`/`SceneScreenplay` models, metadata-based shortlisting, required-beat checks, an independent model review, and an ordered renderer. `scripts/scene_cli.py blueprint --brief '…' --output blueprint.json` generates a blueprint; edit and review it, assign voice IDs from the available account, then use `scripts/scene_cli.py render --blueprint blueprint.json --output DIR --music MUSIC.mp3 --ambience AMBIENCE.mp3 --cover COVER.webp --cast-registry config/cast_registry.json --scope SCENE`. Rendering can incur provider charges. It reuses cached individual event assets when inputs have not changed. `scripts/regression_scene.py hut` and `tower` reproduce the two regression examples using account-available British voice metadata and previously generated backgrounds; no actor impersonation is requested.

Casting reports and saved short auditions are evidence, not confirmation of a voice's accent, age, depth, texture, or acting. Human listening remains required. Long objective instructions are not included in synthesis tags because the provider can read them aloud; the concise `delivery` tag guides synthesis while other acting fields remain documented direction for review. The renderer sequences actions and independently layered backgrounds, supports declared silence and a hard music stop, but does not yet implement arbitrary overlapping actions, word-level semantic anchors inside a spoken event, guaranteed emotion or accent, automatic acoustic verification, or proof of narrative quality. Required-beat IDs and model review are useful checks rather than proof that the generated audio conveys the scene. Review SFX and casting by ear before use.


## Contextual performances and cast registry

`config/cast_registry.json` stores the locked narrator and scene-specific character assignments. The narrator was recovered from the earlier Hagrid scene; locked selections cannot be changed by metadata ranking. The hut currently assigns the same George voice to narrator and Hagrid; this is flagged for a human casting decision. Character metadata is not proof of accent or acting quality.

Adjacent dialogue/reaction events are generated together using ElevenLabs Text to Dialogue. An action, narration, or pause ends a block; provider speaker timestamps resolve individual turns and missing alignment is reported rather than guessed. Independent Whisper word transcription compares each block and the final master to the script, flags inserted, missing or repeated phrases, and retries a suspected repeated block without regenerating unrelated assets. A second ASR opinion is requested for suspicious results. Both ASR systems can miss or hallucinate repetitions; listen to the final master before approval. `scripts/render_performance_fixed.py hut` or `tower` reuses saved music and SFX, preserves the earlier master, and writes `master_performance_fixed.mp3` and `performance_fixed/` QA artifacts. These commands call paid audio and transcription services as needed.
