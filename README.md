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
