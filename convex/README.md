# Fablet Convex backend

This is the backend only. The authoritative consumer and worker contract is in the project plan. Convex is the sole job queue. Functions live in `functions/`; this package directory is the Convex project root. Do not run the Convex CLI from the parent directory. The checked-in `_generated` TypeScript files are bootstrap bindings; the Convex CLI regenerates them for the selected deployment.

## Install and deploy

1. Install Node.js 22 or 24 and npm. From this directory run `npm ci`, then `npx convex dev`. Sign into Convex and select/create a project when prompted. The first push can run with no identity providers, but all consumer functions will reject unauthenticated callers. Convex creates a local `.env.local` deployment selection; keep it private.
2. In the Convex dashboard for that deployment, add the variables below. Restart `npx convex dev` or run `npx convex dev --once` after setting auth variables so the auth configuration is applied. Set variables separately on production before `npx convex deploy`; never commit credentials. Use the dashboard to avoid putting secrets in shell history.
3. Configure the native app's Convex deployment URL and authenticate through the identity provider. Use the separate Convex **HTTP Actions** site URL (`https://<deployment>.convex.site/worker`) as `WORKER_BASE_URL`, not the `.convex.cloud` client URL. Give the worker its API key privately. Production deployments and development deployments have separate URLs and variables.
4. Run `npm run typecheck` and `npm test`. Tests use a mock Convex backend and mocked R2; they do not deploy or validate external credentials.

## Identity and environment

| Variable               | Required                    | Purpose                                                                                                  |
| ---------------------- | --------------------------- | -------------------------------------------------------------------------------------------------------- |
| `AUTH_ISSUER`          | For consumer access         | Exact HTTPS OIDC issuer URL; it must expose discovery and signing keys.                                  |
| `AUTH_AUDIENCE`        | For consumer access         | Exact intended JWT `aud` for this application.                                                           |
| `WORKER_API_KEY`       | For worker calls            | Shared random secret, at least 32 characters; generate at least 256 bits with a secure random generator. |
| `R2_ACCOUNT_ID`        | For completion and playback | Cloudflare's 32-hex-character account ID.                                                                |
| `R2_BUCKET`            | For completion and playback | Private R2 bucket name.                                                                                  |
| `R2_ACCESS_KEY_ID`     | For completion and playback | R2 S3 credential with read/HEAD access to the bucket.                                                    |
| `R2_SECRET_ACCESS_KEY` | For completion and playback | Corresponding server-only secret.                                                                        |

Both auth variables must be set together. No provider or demo identity is assumed. Provision a real OIDC provider (for example, an appropriately configured Clerk/Auth0 tenant) that supplies signed ID tokens with the exact issuer and audience above. Wire its persistent login and token refresh into the native Convex client; a user-supplied ID or an unsigned locally constructed token is not authentication. Ownership uses the validated issuer-and-subject `tokenIdentifier`, so replacing an issuer changes ownership. No public production mode is implemented.

Configure the R2 bucket as private, with a server credential restricted to read/HEAD only; issue the worker separate, narrowly scoped upload credentials. Upload MP3 with `Content-Type: audio/mpeg` and cover with `Content-Type: image/webp` or `image/jpeg`. R2's S3 endpoint must support byte ranges for player seeking. Playback uses 15-minute signed GET URLs, with the returned common refresh time 30 seconds earlier; URLs are bearer secrets, so do not log or persist them unnecessarily. Keys and R2 credentials never appear in consumer summaries.

## Worker integration

All requests are POST JSON with `Authorization: Bearer <WORKER_API_KEY>`. Claim returns HTTP 204 when empty, otherwise a 256-bit random lease token. Claim is a single transactional mutation, leases last 10 minutes, and heartbeats renew them. Report progress as real milestones in the documented 0–100 range; progress cannot decrease within an attempt. Only the current unexpired token can update or fail a job. A one-minute cron processes up to 100 expired leases per run: the first expiration requeues with progress reset; the second marks the job failed. Owner-initiated retry resets the attempt counter.

On completion, the backend checks the manifest key prefix and rejects path traversal, then HEADs both objects for nonzero size using R2 credentials. It rechecks the lease in the same transaction as publication. A repeated completion succeeds only with the same manifest and the same completing lease token. Missing/empty objects produce 409; storage/configuration outages produce 503. Bad payloads produce 400, invalid worker auth 401, unknown jobs 404, and stale leases or invalid state 409. The worker's error details remain internal; users see a generic safe failure message. Lease tokens and worker credentials must not be embedded in the app.

## Important storage limitation

The frozen contract gives workers direct object-store write access and names shared final objects `productions/<id>/master.mp3` and `productions/<id>/cover.webp`. Convex can reject stale _manifest publication_, but it cannot revoke a worker's independent R2 write credentials or atomically couple an R2 upload/HEAD with a Convex transaction. A stale or compromised worker could overwrite final bytes before or after completion, including between HEAD and publication. Therefore this implementation **does not guarantee immutable published audio or protection from stale object overwrites**, even though it rejects stale completion requests. Do not use this setup for adversarial/multi-worker production without a reviewed storage protocol change: use immutable per-attempt object keys plus narrowly scoped, short-lived write credentials and/or an independently enforced conditional promotion mechanism. The worker should stop on lease loss, use private attempt-specific work prefixes, and avoid writing shared final keys after lease loss, but this operational rule alone is not an enforceable guarantee. The fixed manifest contract must be reviewed before changing the final layout or upload flow.

R2 HEAD only verifies object existence and nonzero length at the time of the check, not format, duration, licensing, quality, or future integrity. Real R2 connectivity, JWT verification, physical-device playback/seek, scheduling, concurrent behavior on a deployed Convex instance, and the end-to-end native/worker integration require deployment-specific tests and have not been verified by the local mock tests.

## Additional operational limits

- A lost claim response consumes a lease attempt until the lease expires; claim is not idempotent. An idempotent recovery protocol would require agreement with the worker owner.
- There is no per-user quota or production budget. Restrict signups and monitor usage before connecting paid generation services.
- The backend enforces nondecreasing percentage within an attempt, but does not enforce stage ordering or reserve 100% for completion. Workers must report truthful stages and percentages.
- Worker request bodies are size-checked after buffering. Apply upstream request limits before exposing this service broadly.
