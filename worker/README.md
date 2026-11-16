# Fablet production worker

This single-process worker claims one Convex job at a time, searches Wikipedia for background, writes original narration with an OpenAI-compatible chat model, synthesizes MP3 speech with the provider's speech API, concatenates it with FFmpeg, creates a simple original WebP cover, and uploads both to private S3-compatible storage. It reports research, writing, narration, assembly, and basic quality checking. No fact checking, music, sound effects, editorial review, or listening test is performed. Generated factual claims and titles/descriptions can be inaccurate; review the output before sharing.

## Prerequisites

- Python 3.10 or newer; FFmpeg and ffprobe on `PATH`, with the `libmp3lame` encoder.
- A deployed backend and its worker API key. Set `WORKER_BASE_URL` to the Convex HTTP actions URL ending in `/worker`, not the standard Convex client URL. The backend must be configured with the same key.
- An OpenAI API key with access to chat completions and speech synthesis, or an explicitly compatible provider supporting JSON-object chat responses and the OpenAI speech streaming endpoint. The chosen speech model must accept MP3 output and the chosen voice. Model/API availability and cost depend on the provider.
- A private R2/S3 bucket and credentials permitting `PutObject` and `HeadObject`. The backend playback service must point to the same bucket. The included backend storage implementation specifically requires R2 configuration; alternative S3 endpoints require a compatible backend configured separately. Do not enable public access for private productions.

Create an isolated environment and install dependencies from this directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Set these environment variables securely before starting the worker; do not commit secrets:

| Variable               | Purpose                                                                |
| ---------------------- | ---------------------------------------------------------------------- |
| `WORKER_BASE_URL`      | HTTPS URL ending in `/worker`                                          |
| `WORKER_API_KEY`       | Backend worker key, at least 32 characters                             |
| `WORKER_ID`            | Identifier for this worker, maximum 200 characters                     |
| `OPENAI_API_KEY`       | Provider API key                                                       |
| `OPENAI_TEXT_MODEL`    | JSON-capable chat model, for example `gpt-4o-mini`                     |
| `OPENAI_TTS_MODEL`     | Speech model, for example `tts-1`                                      |
| `OPENAI_TTS_VOICE`     | Supported voice, for example `alloy`                                   |
| `S3_ENDPOINT_URL`      | HTTPS endpoint, for R2 `https://<account-id>.r2.cloudflarestorage.com` |
| `S3_BUCKET`            | Private bucket name                                                    |
| `S3_ACCESS_KEY_ID`     | Storage access key                                                     |
| `S3_SECRET_ACCESS_KEY` | Storage secret                                                         |
| `S3_REGION`            | Optional; defaults to `auto` for R2                                    |
| `OPENAI_BASE_URL`      | Optional; defaults to `https://api.openai.com/v1`                      |

Run `python worker.py`. Stop with Ctrl-C. Run the offline tests with `python -m unittest -v test_worker`. The FFmpeg test skips when FFmpeg/ffprobe are unavailable; tests do not call external services.

## Operation and limitations

- The full prompt is sent to the public English Wikipedia search API over HTTPS, so do not submit confidential topics. The worker retrieves up to three short plain-text introductory extracts and supplies them as untrusted context to the model. A search may return no results; network or malformed-response errors fail the attempt. The sources are neither verified nor exhaustive, and model instructions against following source text or inventing citations are not a guarantee. The extracts are not saved as a bibliography or independently checked.
- Supported jobs are only the contract's 5, 10, and 15 minutes. The script targets 130 words per minute; actual audio must be within 70-130% of the requested length or the job fails. This is an approximate guard, not an exact-duration guarantee. The manifest reports the actual duration from ffprobe. A short 60-90-second showcase must be made separately as an excerpt from a real production; one-minute jobs are not supported.
- API calls, provider retries and storage requests have bounded timeouts/retries. Mutating worker requests and storage uploads are not automatically retried; heartbeat requests may retry. The worker renews the ten-minute lease concurrently every 30 seconds, and treats a failed renewal as lease loss. It checks the lease before subsequent work and before each final upload and completion. Provider and object-storage calls already in flight cannot be cancelled reliably, and checking the lease cannot be made atomic with initiating a storage request. The worker does not deliberately begin publication after detecting lease loss.
- The contract requires fixed final object names, and R2 cannot atomically fence writes using the Convex lease. A stale upload already in flight can overwrite a newer attempt even after the worker detects lease loss. Run only one worker and do not restart it until the old process and its outstanding requests have stopped; strict protection requires backend/storage fencing or attempt-specific published keys, which are outside this worker-only change.
- Authenticated worker API calls reject redirects. A claim request is not retried on an ambiguous response; an orphaned lease is recovered by the backend. Completion is attempted once. A definite HTTP 400 rejection is reported as failure only after confirming the lease. HTTP 409 and uncertain outcomes such as timeouts or HTTP 503 do not trigger failure; inspect the job and let backend lease recovery handle unresolved attempts.
- Local script and audio segments exist only in a temporary directory for the active attempt and are removed afterward. There is no durable cache or resume. Partial final uploads can remain after failure; they are not made available by the app until completion. No secrets or raw provider errors are intentionally logged or sent to the backend.
- QA checks nonempty audio, ffprobe duration, a complete FFmpeg decode and peak volume above -60 dBFS, and nonempty uploaded objects. This catches fully silent or extremely quiet masters but not silent sections, clipping, noise, pronunciation, or factual accuracy. Actual provider operation, provider compatibility, rights/terms, and end-to-end playback require separate testing with authorized credentials.
