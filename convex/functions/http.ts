import { httpRouter } from "convex/server";
import { httpAction } from "./_generated/server";
import { internal } from "./_generated/api";
import type { Infer } from "convex/values";
import type { activeStatus, manifest as manifestValidator } from "./schema";

const router = httpRouter();
const stages = new Set(["researching", "writing", "narrating", "scoring", "mixing", "quality_check"]);
const isStage = (x: unknown): x is Infer<typeof activeStatus> => typeof x === "string" && stages.has(x);
type Payload = Record<string, unknown>;
const isObject = (x: unknown): x is Payload => !!x && typeof x === "object" && !Array.isArray(x);
const text = (x: unknown, max: number): x is string => typeof x === "string" && x.trim().length > 0 && x.length <= max;
const response = (status: number, body?: unknown) => body === undefined ? new Response(null, { status }) :
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
async function digest(s: string) {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, "0")).join("");
}
async function authorized(req: Request) {
  const secret = process.env.WORKER_API_KEY;
  const authorization = req.headers.get("Authorization") ?? "";
  if (!secret || secret.length < 32 || !authorization.startsWith("Bearer ") || authorization.length > 4096) return false;
  const [expected, actual] = await Promise.all([digest(secret), digest(authorization.slice(7))]);
  let difference = 0;
  for (let i = 0; i < expected.length; i++) difference |= expected.charCodeAt(i) ^ actual.charCodeAt(i);
  return difference === 0;
}
function validKey(key: unknown, id: string): key is string {
  if (typeof key !== "string" || key.length > 1024 || !key.startsWith(`productions/${id}/`)) return false;
  const parts = key.slice(`productions/${id}/`.length).split("/");
  return parts.every(part => part !== "." && part !== ".." && /^[a-zA-Z0-9._-]+$/.test(part));
}
function validManifest(value: unknown, id: string): value is Infer<typeof manifestValidator> {
  return isObject(value) && text(value.title, 300) && text(value.description, 4000) &&
    typeof value.duration_seconds === "number" && Number.isFinite(value.duration_seconds) && value.duration_seconds > 0 &&
    validKey(value.audio_object_key, id) && validKey(value.cover_object_key, id) && value.audio_object_key !== value.cover_object_key && value.mime_type === "audio/mpeg" &&
    Object.keys(value).every(k => ["title", "description", "duration_seconds", "audio_object_key", "cover_object_key", "mime_type"].includes(k));
}
function resultResponse(result: string) {
  if (result === "not_found") return response(404, { error: "Job not found" });
  if (result === "conflict") return response(409, { error: "Lease expired or job state invalid" });
  return response(200, { ok: true });
}

for (const endpoint of ["claim", "progress", "heartbeat", "complete", "fail"] as const) {
  router.route({ path: `/worker/${endpoint}`, method: "POST", handler: httpAction(async (ctx, req) => {
    if (!await authorized(req)) return response(401, { error: "Unauthorized" });
    let body: unknown;
    try {
      const raw = await req.text();
      if (raw.length > 16_384) return response(400, { error: "Invalid payload" });
      body = JSON.parse(raw);
    } catch { return response(400, { error: "Invalid payload" }); }
    if (!isObject(body)) return response(400, { error: "Invalid payload" });
    try {
      if (endpoint === "claim") {
        if (!text(body.worker_id, 200)) return response(400, { error: "Invalid payload" });
        const bytes = crypto.getRandomValues(new Uint8Array(32));
        const token = Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("");
        const claimed = await ctx.runMutation(internal.worker.claim, { worker_id: body.worker_id, lease_hash: await digest(token) });
        return claimed ? response(200, { ...claimed, lease_token: token }) : response(204);
      }
      if (!text(body.job_id, 200) || !text(body.lease_token, 256)) return response(400, { error: "Invalid payload" });
      const job_id = body.job_id;
      const args = { job_id, lease_hash: await digest(body.lease_token) };
      if (endpoint === "heartbeat") return resultResponse((await ctx.runMutation(internal.worker.heartbeat, args)).result);
      if (endpoint === "progress") {
        if (!isStage(body.status) || typeof body.progress_percent !== "number" ||
          !Number.isFinite(body.progress_percent) || body.progress_percent < 0 || body.progress_percent > 100 || !text(body.stage_message, 500)) {
          return response(400, { error: "Invalid payload" });
        }
        return resultResponse((await ctx.runMutation(internal.worker.progress, { ...args, status: body.status,
          progress_percent: body.progress_percent, stage_message: body.stage_message })).result);
      }
      if (endpoint === "fail") {
        if (!text(body.error_code, 200) || !text(body.error_message, 4000)) return response(400, { error: "Invalid payload" });
        return resultResponse((await ctx.runMutation(internal.worker.fail, { ...args, error_code: body.error_code, error_message: body.error_message })).result);
      }
      if (!validManifest(body.manifest, job_id)) return response(400, { error: "Invalid manifest" });
      const manifest = body.manifest;
      const state = await ctx.runQuery(internal.worker.checkComplete, { ...args, manifest });
      if (state.result !== "ok") return resultResponse(state.result);
      const exists = await ctx.runAction(internal.storage.verifyAssets, { audio: manifest.audio_object_key, cover: manifest.cover_object_key });
      if (!exists) return response(409, { error: "Assets missing or empty" });
      // Recheck the lease in the same transaction as the final state change.
      return resultResponse((await ctx.runMutation(internal.worker.complete, { ...args, manifest })).result);
    } catch (error) {
      console.error("Worker request failed", endpoint, error);
      return response(503, { error: "Backend unavailable" });
    }
  }) });
}
export default router;
