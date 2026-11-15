# AI-Native Audiobook Studio — Two-Person Build Plan (v2)

**Date:** November 15, 2026  
**Status:** Implementation-ready API and ownership contract  
**Product:** A listener describes an interest, commissions a quality-first narrated and scored audio documentary, and listens once production has finished.

## Decisions — do not leave these open

1. **Asynchronous generation, never live audio generation.** `Create` immediately returns a production ID. Research, scriptwriting, voice, score, SFX, mixing, cover art, and QA run in a background worker.
2. **One authoritative queue:** **Convex** is the source of truth for jobs, status, library metadata, and user-facing progress. The Python worker **polls and leases** work through authenticated backend HTTP endpoints. Do **not** add Inngest, Redis, BullMQ, or a second queue for the hackathon; that's unnecessary coordination overhead. Reconsider a managed workflow orchestrator later if retries/fan-out become complex.
3. **Ownership:** **Teammate** builds the entire consumer app, Convex job API/schema, player, library, and the worker-facing HTTP endpoints. **You** build the Python production worker, orchestration, audio processing/QA, cover generation, and upload final artifacts to shared object storage.
4. **Storage:** Cloudflare R2 (or S3-compatible storage) for finished MP3/cover. **Worker uploads final assets; app owns how users access them.** The manifest stores object keys, not expiring URLs.
5. **Production format:** One complete MP3 and one cover WebP/JPEG per job in v1. Optional chapters and transcripts can be added without changing the core flow.
6. **Demo honesty:** Show a **new real job** submitted and picked up, with genuine progress; separately open a **previously completed** book and play it. No claim that a 10-minute audiobook can be finished in a 30-second demo.
7. **Privacy and rights:** Use original, generated scripts/music/audio or properly licensed material. Do not clone voices without consent. Do not call copyrighted existing audiobook text a generated original work.

---

## 1. Responsibilities and deliverables

| Area | Owner: Teammate — app and job service | Owner: You — production engine |
|---|---|---|
| User experience | Prompt input, style/length selectors, submit, status tracker, cover, library, audio player, persistence | No frontend work required |
| Backend contract | Convex schema, create/list/get queries or mutations, authenticated worker HTTP endpoints, job leasing/heartbeats, status updates | Python client for worker endpoints; obey schemas and lease rules |
| Jobs | Durable queue, lease exclusivity, retries/status transitions, terminal states, truthful progress display | Poll/claim job, generate assets, report real milestones, handle stage errors and retryable failures |
| Creative pipeline | Display resulting title, description, duration | Research/sources, outline, script revision, narration, score, SFX, mix/master, cover, quality checks |
| Assets | Define storage bucket keys and serving strategy; issue playback URLs; deal with expired URLs | Upload MP3 + image to agreed keys; verify they exist before publishing |
| Tests | UI/contract tests, mock worker, Revyl end-to-end app flows | Script/audio tests, provider adapter tests, FFmpeg analysis, full render smoke test |
| Demo | Polished app, live submit/progress, previously completed audiobook playback | Run real worker during demo, prep and quality-check 2–3 completed showcase productions |

**Workload:** This is deliberately asymmetric. Your production engine carries more technical/creative uncertainty; teammate's work is still a complete, substantial feature with backend state and workflow correctness.

**Definition of independent success**
- Teammate: With a **mock worker**, can submit a job, see accurate queued/processing/completed states, see a library card, and play an uploaded demo MP3 with its cover.
- You: With a **curl/CLI-created job or tiny test harness**, can claim a job, generate the finished artifacts, upload them, and publish the output manifest through the API.

---

## 2. System architecture

```text
User browser / mobile-friendly Next.js app                 [TEAMMATE]
    |
    | createProduction(prompt, settings)
    v
Convex: productions table + user/library queries         [TEAMMATE]
    |                                     ^
    | queued job                          | status, heartbeat, publish
    v                                     |
Authenticated worker HTTP endpoints (Convex HTTP actions) [TEAMMATE]
    ^                                     |
    | lease / claim / report / complete    |
    v                                     |
Python production worker                                  [YOU]
  brief -> research -> story -> script -> TTS -> music/SFX
        -> FFmpeg mix/master -> audio QA -> cover art
    |
    | upload MP3 + cover with S3-compatible SDK
    v
Cloudflare R2 (finished assets; source files optional)    [SHARED]
    ^
    | app backend issues/returns playback-access URLs
    |
User's player                                              [TEAMMATE]
```

**Important separation:** The worker must never modify Convex state directly using privileged frontend permissions. It calls dedicated worker endpoints authenticated with `WORKER_API_KEY`. The app must never expose that key to a browser.

---

## 3. Fixed API contract (v1)

### 3.1 Data types and defaults

```ts
type ProductionStatus =
  | "queued"
  | "researching"
  | "writing"
  | "narrating"
  | "scoring"
  | "mixing"
  | "quality_check"
  | "completed"
  | "failed";

type Style = "cinematic_documentary" | "calm_explainer";

type CreateProductionInput = {
  prompt: string;                    // trim; 10–2000 characters
  duration_minutes?: 5 | 10 | 15;   // default: 10
  style?: Style;                     // default: cinematic_documentary
};

type ProductionSummary = {
  id: string;                        // opaque, stable production ID
  status: ProductionStatus;
  progress_percent: number;          // 0–100; indicative, not ETA
  stage_message: string;             // e.g. "Drafting the narrative"
  created_at: string;                // ISO-8601 UTC
  updated_at: string;                // ISO-8601 UTC
  prompt: string;
  duration_minutes_requested: number;
  style: Style;
  title: string | null;
  description: string | null;
  duration_seconds: number | null;   // actual final audio duration
  cover_url: string | null;          // only populated once ready
  audio_url: string | null;          // only populated once ready; URL may expire
  error_message: string | null;      // user-safe reason if failed
};
```

**Transport decision:** Consumer-side functions use **Convex mutations/queries** rather than custom REST calls. Worker-side functions are **HTTP** to accommodate Python. That is one backend with two interfaces, not two separate job services.

### 3.2 Consumer contract (implemented by teammate)

**Mutation** `productions.create(input: CreateProductionInput): { id: string, status: "queued" }`

- Validates input and authenticates/associates the current demo user/session.
- Creates a durable record with `status=queued`, `progress_percent=0`.
- **Returns immediately**, without calling any model or audio generator.
- Idempotency for accidental double clicks can be handled by disabling submit while pending; stronger idempotency can be added later.

**Query** `productions.get({ id }): ProductionSummary | null`

- Reactive: the screen automatically updates as Convex status fields change.
- Enforces ownership for non-public productions.
- Only returns valid playback/cover URLs when completed; regenerate short-lived download URLs when needed.

**Query** `productions.list({ limit?: number }): ProductionSummary[]`

- Most recent first; includes queued, processing, failed, and completed jobs.
- Default limit 20; allow navigating to a detail screen.

**Mutation** `productions.retry({ id }): { id: string, status: "queued" }` (optional for hackathon)

- Allowed only for a failed production owned by the current user; resets job for a clean rerun.

### 3.3 Worker contract (implemented by teammate, consumed by you)

**Base URL:** `https://<deployment-host>/worker` (configurable as `WORKER_BASE_URL`). The production ID is a string, not assumed to be a UUID.

**Auth:** `Authorization: Bearer <WORKER_API_KEY>`. All worker endpoints reject missing/invalid credentials. Secrets are server-side environment variables only.

**POST `/worker/claim`**

Request:
```json
{ "worker_id": "audio-worker-1" }
```

Response if a job is available:
```json
{
  "job": {
    "id": "prod_example123",
    "prompt": "The Fermi Paradox, told as a cinematic mystery",
    "duration_minutes": 10,
    "style": "cinematic_documentary"
  },
  "lease_token": "opaque-secret-lease-token",
  "lease_expires_at": "2026-11-15T22:10:00Z"
}
```

If no job is available: **HTTP 204 No Content**.

**Behavior:** Atomically claim the oldest eligible queued job, set `status=researching`, store `worker_id`, issue a random `lease_token`, and set a **10-minute lease**. Two workers must never claim the same active job. In the demo, run one worker and limit concurrency to 1.

**POST `/worker/progress`**

```json
{
  "job_id": "prod_example123",
  "lease_token": "opaque-secret-lease-token",
  "status": "writing",
  "progress_percent": 30,
  "stage_message": "Revising the script"
}
```

- Accepted statuses: `researching`, `writing`, `narrating`, `scoring`, `mixing`, `quality_check`.
- Valid lease token required; update `updated_at`; reject progress after job is terminal.
- `progress_percent` is a coarse milestone indicator, **not** a model-derived countdown or completion forecast.

**POST `/worker/heartbeat`** (at least every 2 minutes while working)

```json
{ "job_id": "prod_example123", "lease_token": "opaque-secret-lease-token" }
```

- Extends the active job's 10-minute lease.
- Return `409` if the lease expired or was replaced. The worker stops publishing if it loses the lease.

**POST `/worker/complete`**

```json
{
  "job_id": "prod_example123",
  "lease_token": "opaque-secret-lease-token",
  "manifest": {
    "title": "The Great Silence",
    "description": "A cinematic journey through the Fermi Paradox.",
    "duration_seconds": 612,
    "audio_object_key": "productions/prod_example123/master.mp3",
    "cover_object_key": "productions/prod_example123/cover.webp",
    "mime_type": "audio/mpeg"
  }
}
```

- **Prerequisite:** Both assets have finished uploading; worker checks object existence and nonzero bytes.
- Backend verifies that the supplied object keys belong under `productions/<job_id>/` and, where possible, performs a storage HEAD check.
- Atomically store manifest + `status=completed` + `progress_percent=100`.
- The consumer backend maps object keys to accessible URLs; the worker does **not** publish expiring signed URLs in the manifest.

**POST `/worker/fail`**

```json
{
  "job_id": "prod_example123",
  "lease_token": "opaque-secret-lease-token",
  "error_code": "TTS_PROVIDER_FAILED",
  "error_message": "Narration generation failed after retries"
}
```

- Store internal diagnostic code/details separately from user-safe `error_message`.
- Set `status=failed`; the app offers a retry mechanism or a clear failure message.

**HTTP semantics:** `200` for success, `204` for empty claim, `400` for bad payload, `401` for unauthorized worker, `404` for unknown job, `409` for stale lease/invalid state; idempotent `complete` with the **same** manifest can safely return success again when the job is already complete. Do not permit old workers to overwrite newer attempts.

### 3.4 Job lifecycle and state transition policy

```text
queued
  -> researching -> writing -> narrating -> scoring -> mixing
  -> quality_check -> completed
       |             |             |
       +-------------+-------------+----> failed

failed --(user retries)--> queued
```

Note: **Cover art may be generated in parallel** with the other stages; it is not a required visible job status. Music and narration can internally parallelize too, but status reflects the most useful current stage, not a guarantee every subtask is sequential.

Suggested **indicative milestone percentages**: queued 0, researching 10, writing 25, narrating 45, scoring 65, mixing 80, quality_check 92, completed 100. Use monotonically nondecreasing progress. Never make progress look like a guaranteed ETA.

**Stalled jobs:** A server-side scheduled task finds leases that have expired. For MVP: requeue the job if `attempt_count < 2`, otherwise mark failed. A worker that later finishes with an expired lease **cannot** publish. Worker upload keys should be attempt-specific internally or old outputs must not overwrite current completed output. Safe simple approach: use attempt-specific temp prefixes, then publish final keys only while holding a current lease.

**Worker polling:** Every 5 seconds for demo; slower outside demos. When there's no job, keep polling. This is *not* realtime content generation—the worker only begins asynchronous production.

### 3.5 Final asset contract

Required object storage layout:

```text
productions/<production_id>/master.mp3
productions/<production_id>/cover.webp
```

Optional internal artifacts (kept private, not required by UI):

```text
work/<production_id>/<attempt_id>/research.json
work/<production_id>/<attempt_id>/script.json
work/<production_id>/<attempt_id>/narration/*.wav
work/<production_id>/<attempt_id>/music/*.wav
work/<production_id>/<attempt_id>/sfx/*.wav
work/<production_id>/<attempt_id>/qa_report.json
```

**Serving decision for MVP:** Publicly shareable demo productions may use unguessable, publicly readable object URLs; for user-private creations use backend-issued short-lived signed URLs and refresh them when needed for long playback. Store only keys in Convex. Set `Content-Type: audio/mpeg` for MP3 and `image/webp` for covers, and ensure byte-range requests work for seeking. Keep R2 credentials private and narrowly scoped.

---

## 4. User experience (teammate)

### Screen A — Create
- Large prompt input: **"What are you curious about?"**
- Duration default 10 min; style default cinematic documentary.
- Create button calls `productions.create` and immediately navigates to `/productions/<id>`.

### Screen B — Job detail
- While queued: **"In the production queue"** (do not imply research has started).
- During processing: stage name, descriptive status, coarse progress indicator, and note **"This is a quality-first production; your audiobook will appear here when ready."**
- On failure: clear user-safe message and optional retry.
- When completed: title, cover, duration, description, and playback controls.
- Never simulate progress based on elapsed time. Display **only backend-reported** state.

### Screen C — Library
- Cards for **all** productions, including pending ones.
- Completed cards have cover, title, duration, and Play button.
- In-progress cards show their actual current stage.
- Persist pause/seek position locally first; optional account sync later.

### Player requirements
- HTML5 audio with play/pause, seek/scrub, current/total time, volume where useful.
- Handle buffering, network errors, expired signed URLs, and reload resume.
- Good mobile layout; avoid attempting advanced cross-platform background playback guarantees for the demo.

---

## 5. Production engine (you)

### Worker loop

```python
while True:
    claimed = claim_job()               # 204 => no job
    if not claimed:
        sleep(5)
        continue

    job, lease = claimed
    start_heartbeat_loop(job.id, lease) # every <= 120s
    try:
        research = research_sources(job.prompt)
        progress(job, lease, "writing", 25, "Writing and revising the story")
        script = draft_and_edit(research, job)
        progress(job, lease, "narrating", 45, "Recording narration")
        narration = synthesize_voice(script)
        progress(job, lease, "scoring", 65, "Producing music and sound design")
        music, sfx = create_audio_elements(script)
        progress(job, lease, "mixing", 80, "Mixing the audio")
        audio = render_mix(narration, music, sfx)
        progress(job, lease, "quality_check", 92, "Checking the finished production")
        qa(audio, script)
        cover = generate_cover_art(script)
        keys = upload_final_assets(job.id, audio, cover)
        complete(job, lease, manifest_from(keys, audio, script))
    except LeaseLost:
        discard_result_without_publishing()
    except Exception as exc:
        fail(job, lease, safe_error(exc))
```

The above is illustrative: update `researching` immediately when claimed, renew the lease **concurrently** throughout every long model/audio API call, and cache every stem and script segment so retries don't waste the entire production.

### Quality gates
- Script: factual/source checks, narrative coherence, no long repetitive passages, clear opening and ending.
- TTS: segments generated in expected order, text/audio alignment, pronunciation review for names.
- Music: instrumental only unless explicitly requested; recurring musical motifs; duck under narration.
- Effects: selective and contextually appropriate; prefer curated assets when reliable.
- Mix: no clipping or truncated assets; fades, consistent perceived loudness, silence checks; duration measured from actual master audio.
- Publish only after the master and cover are durable and QA passes.

### Service choices (benchmark, don't hard-lock without checking access and commercial terms)
- Research/script: capable reasoning LLM with source retrieval, editorial passes.
- Narration: ElevenLabs, benchmark against another expressive TTS provider.
- Score: licensable AI music API with reliable instrumental output.
- SFX: generated effects plus a curated licensed asset library.
- Assembly: Python + FFmpeg; object storage with S3-compatible uploads.
- Image: licensed/generated cover art, output WebP.

**Quality-first:** Generate entire audio offline, with multiple passes where needed. No realtime voice streaming is necessary.

---

## 6. Concrete parallel work plan

### Milestone 0 — Contract + skeleton (do first)
**Teammate:** Initialize Next.js + Convex; create schema, consumer mutations/queries, empty worker endpoints; use test credentials and a local/demo environment.  
**You:** Build Python worker CLI, typed `claim/progress/heartbeat/complete/fail` client, storage uploader, fixtures.  
**Integration test:** Create a job -> mock worker claims -> reports two statuses -> uploads known sample MP3/cover -> completes -> frontend plays it.

### Milestone 1 — Two independent vertical slices
**Teammate:** Polished Create, detail/status, library, player; reactive updates and mock completed content.  
**You:** Render a high-quality 60–90-second documentary with researched script, expressive voice, intentional music, restrained SFX, and final master/cover.

### Milestone 2 — Real end-to-end async production
Connect the worker to the actual queue. Run a real request in the app, observe real status transitions, and publish a newly generated master/cover. Create a longer 8–12-minute showcase production offline and listen through the whole artifact.

### Milestone 3 — Demo readiness and failure recovery
Test empty queue, duplicate button clicks, worker restart, expired lease, failure and retry, partial upload, expired signed URL, and stale producer completing late. Prepare 2–3 excellent completed works in the same app used for new requests.

---

## 7. Hackathon demo — authentic asynchronous story

**Prior to demo:** Generate and quality-check 2–3 showcase audiobooks using the real worker, with distinctive covers and contrasting topics. Keep them in the same Convex-backed library, labeled by their actual completion state. Ensure all assets actually play.

**On stage (approximately 60–90 seconds; adapt to available slot):**

1. **0–15 seconds:** Enter a novel audience-suggested prompt, choose style, click **Create**. A new job appears in the library as **Queued**.
2. **15–35 seconds:** The real worker claims it; the page reactively changes to **Researching** (or whichever step it has genuinely reached). Show the server-side worker log/trace briefly if desired. **Do not wait for rendering to finish.**
3. **35–65 seconds:** Click a **Previously Completed** production. Show title, cover, duration, play the best 15–25-second excerpt with narration + score + subtle SFX.
4. **65–90 seconds:** Show another finished book with a different style or topic. Explain that the exact same asynchronous pipeline creates new productions and stores them here when completed.

**Stage-friendly one-liner:** *"We just commissioned a new audiobook; it's producing in the background. Here's a completed one made by the same system, with the script, voices, score, and mix all generated and quality-checked."*

**Don't fake:** Never animate a job through stages independent of the backend; never say the just-submitted job produced an earlier prerecorded file. No time-to-finish promise without measured data.

---

## 8. Engineering acceptance checklist

- [ ] Frontend `create` returns and displays a real job ID without starting media generation inline.
- [ ] Convex has one authoritative jobs table and atomic exclusive leasing.
- [ ] Worker endpoints are authenticated; secrets never reach browser bundles.
- [ ] A Python worker can claim work, heartbeat, report stage, fail, and complete it.
- [ ] UI reflects **actual** Convex state via subscriptions (not fictional progress).
- [ ] Job survives app refresh, worker crash, and a delayed audio-generation step.
- [ ] An expired lease cannot publish over a newer attempt.
- [ ] Final manifest includes title, description, actual duration, MP3 key, cover key.
- [ ] MP3 plays and seeks on mobile; cover image appears in library and detail page.
- [ ] A failed stage produces a truthful failure state or controlled retry.
- [ ] One **new** job can be demonstrated live; at least two **completed** jobs have excellent audible samples.
- [ ] Full quality check performed on the rendered showcase, not only the first 20 seconds.

---

## 9. Scope boundaries / non-goals

**Build now:** Single-user-friendly demo, async jobs, one MP3 + cover, style/duration choices, reactive status, library, reliable player, high-quality 8–12-minute samples.

**Do not build now:** Real-time synthesized audiobook streams; automatic generation of new UI widgets; public social network; marketplace; paid subscriptions; ten providers per media category; complex editing timeline in browser; word-by-word subtitles; universal voice cloning; multi-hour output; high-throughput production clusters.

**Sponsor tools:** Convex can be part of the runtime backend. Capy is used to implement or improve the app and production code; Revyl is used to validate real user flows. Neither needs an invented per-request runtime role.

---

## 10. Initial handoff messages

**Send teammate:**  
> You own the Next.js consumer app **and** its Convex jobs backend. Implement `productions.create/get/list`, the authenticated worker endpoints (`claim`, `progress`, `heartbeat`, `complete`, `fail`), and the UI that submits prompts, displays real queued/processing/completed status, and plays completed MP3+cover URLs. The API contract in Section 3 is frozen for v1. Develop using a mock worker and sample MP3 until my production engine is ready. For the demo, we submit a real queued job and play a previously finished book.

**Your own implementation target:**  
> Build a Python worker with the worker HTTP client, durable heartbeat, research → script → voice/music/SFX → mix/QA → cover stages, R2 upload, and manifest publication. Optimize for editorial/audio quality, not immediate response. First ship a fully scored 60–90-second sample, then the 8–12-minute complete documentary.

**Shared merge rule:** Any breaking change to `CreateProductionInput`, worker endpoint payloads, status names, or manifest keys requires an explicit review by both people. Everything behind those interfaces can evolve independently.
