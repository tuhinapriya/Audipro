import { beforeEach, afterEach, describe, expect, test, vi } from "vitest";
import { convexTest } from "convex-test";
import schema from "../functions/schema";
import { api, internal } from "../functions/_generated/api";

const modules = import.meta.glob("../functions/**/!(*.*.*)*.*s");
const secret = "correct-worker-secret-at-least-32-characters";
let headLength = 10;
vi.mock("@aws-sdk/client-s3", () => ({
  S3Client: class { async send() { return { ContentLength: headLength }; } destroy() {} },
  GetObjectCommand: class { constructor(public args: unknown) {} },
  HeadObjectCommand: class { constructor(public args: unknown) {} },
}));
vi.mock("@aws-sdk/s3-request-presigner", () => ({ getSignedUrl: async (_client: unknown, command: { args: { Key: string } }) => `https://signed.example/${command.args.Key}` }));

function setup() {
  const t = convexTest(schema, modules);
  const alice = t.withIdentity({ subject: "alice", issuer: "https://issuer.example", tokenIdentifier: "https://issuer.example|alice" });
  const bob = t.withIdentity({ subject: "bob", issuer: "https://issuer.example", tokenIdentifier: "https://issuer.example|bob" });
  const post = (path: string, data: unknown, key = secret) => t.fetch(`/worker/${path}`, { method: "POST", headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" }, body: JSON.stringify(data) });
  return { t, alice, bob, post };
}
async function createAndClaim(s: ReturnType<typeof setup>) {
  const created = await s.alice.mutation(api.productions.create, { prompt: "  An interesting history  " });
  const res = await s.post("claim", { worker_id: "worker-a" });
  expect(res.status).toBe(200);
  return { ...created, ...(await res.json()) };
}
function manifest(id: string) {
  return { title: "Title", description: "Description", duration_seconds: 612,
    audio_object_key: `productions/${id}/master.mp3`, cover_object_key: `productions/${id}/cover.webp`, mime_type: "audio/mpeg" };
}
beforeEach(() => {
  process.env.WORKER_API_KEY = secret;
  process.env.R2_ACCOUNT_ID = "a".repeat(32);
  process.env.R2_BUCKET = "test";
  process.env.R2_ACCESS_KEY_ID = "test";
  process.env.R2_SECRET_ACCESS_KEY = "test";
  headLength = 10;
});
afterEach(() => { delete process.env.WORKER_API_KEY; });

describe("consumer and worker contract", () => {
  test("requires identity, enforces ownership, defaults, validation and ordering", async () => {
    const s = setup();
    await expect(s.t.mutation(api.productions.create, { prompt: "a valid long prompt" })).rejects.toThrow("Authentication required");
    await expect(s.alice.mutation(api.productions.create, { prompt: " short " })).rejects.toThrow();
    const first = await s.alice.mutation(api.productions.create, { prompt: "  First valid prompt  " });
    await s.bob.mutation(api.productions.create, { prompt: "Another valid prompt" });
    expect(await s.bob.query(api.productions.get, { id: first.id })).toBeNull();
    expect(await s.alice.query(api.productions.get, { id: first.id })).toMatchObject({ prompt: "First valid prompt", duration_minutes_requested: 10, style: "cinematic_documentary", assets_available: false });
    expect(await s.alice.query(api.productions.list, {})).toHaveLength(1);
    await expect(s.alice.action(api.productions.getPlaybackUrl, { id: first.id })).rejects.toThrow();
    await expect(s.bob.action(api.productions.getPlaybackUrl, { id: first.id })).rejects.toThrow();
  });
  test("authenticates worker, claims oldest, handles progress, heartbeat and safe failure", async () => {
    const s = setup();
    expect((await s.post("claim", { worker_id: "x" }, "wrong")).status).toBe(401);
    expect((await s.post("claim", {})).status).toBe(400);
    expect((await s.post("claim", { worker_id: "x" })).status).toBe(204);
    const c = await createAndClaim(s);
    expect(c.job.id).toBe(c.id);
    expect((await s.post("claim", { worker_id: "other" })).status).toBe(204);
    const lease = { job_id: c.id, lease_token: c.lease_token };
    expect((await s.post("heartbeat", { ...lease, lease_token: "wrong" })).status).toBe(409);
    expect((await s.post("progress", { ...lease, status: "writing", progress_percent: 30, stage_message: "Drafting" })).status).toBe(200);
    expect((await s.post("progress", { ...lease, status: "writing", progress_percent: 20, stage_message: "Backwards" })).status).toBe(409);
    expect((await s.post("progress", { ...lease, status: "completed", progress_percent: 100, stage_message: "No" })).status).toBe(400);
    expect((await s.post("heartbeat", lease)).status).toBe(200);
    expect((await s.post("fail", { ...lease, error_code: "INTERNAL", error_message: "secret internal details" })).status).toBe(200);
    expect((await s.alice.query(api.productions.get, { id: c.id }))?.error_message).not.toContain("secret");
    expect((await s.post("heartbeat", lease)).status).toBe(409);
    await expect(s.bob.mutation(api.productions.retry, { id: c.id })).rejects.toThrow();
    expect((await s.alice.mutation(api.productions.retry, { id: c.id })).status).toBe("queued");
  });
  test("a queue entry is leased to at most one of two concurrent claims", async () => {
    const s = setup();
    await s.alice.mutation(api.productions.create, { prompt: "A valid single queue entry" });
    const responses = await Promise.all([
      s.post("claim", { worker_id: "one" }), s.post("claim", { worker_id: "two" }),
    ]);
    expect(responses.map(r => r.status).sort()).toEqual([200, 204]);
  });
  test("expired leases requeue once and then fail, stale workers cannot publish", async () => {
    const s = setup();
    const a = await createAndClaim(s);
    const expire = async () => s.t.run(async ctx => { const id = ctx.db.normalizeId("productions", a.id)!; await ctx.db.patch(id, { lease_expires_at: Date.now() - 1 }); });
    await expire();
    expect((await s.post("heartbeat", { job_id: a.id, lease_token: a.lease_token })).status).toBe(409);
    await s.t.mutation(internal.worker.recoverExpired, {});
    const res = await s.post("claim", { worker_id: "worker-b" });
    const b = await res.json();
    expect(b.job.id).toBe(a.id);
    expect((await s.post("complete", { job_id: a.id, lease_token: a.lease_token, manifest: manifest(a.id) })).status).toBe(409);
    await expire();
    await s.t.mutation(internal.worker.recoverExpired, {});
    expect((await s.alice.query(api.productions.get, { id: a.id }))?.status).toBe("failed");
    expect((await s.post("claim", { worker_id: "worker-c" })).status).toBe(204);
  });
  test("verifies asset keys and nonzero HEAD; completion is idempotent only for same lease and manifest", async () => {
    const s = setup(), a = await createAndClaim(s);
    const lease = { job_id: a.id, lease_token: a.lease_token };
    const m = manifest(a.id);
    expect((await s.post("complete", { ...lease, manifest: { ...m, audio_object_key: `productions/${a.id}/../other` } })).status).toBe(400);
    headLength = 0;
    expect((await s.post("complete", { ...lease, manifest: m })).status).toBe(409);
    headLength = 10;
    expect((await s.post("complete", { ...lease, manifest: m })).status).toBe(200);
    expect((await s.post("complete", { ...lease, manifest: m })).status).toBe(200);
    expect((await s.post("complete", { ...lease, manifest: { ...m, title: "Different" } })).status).toBe(409);
    expect((await s.post("complete", { ...lease, lease_token: "wrong", manifest: m })).status).toBe(409);
    const p = await s.alice.query(api.productions.get, { id: a.id });
    expect(p).toMatchObject({ status: "completed", progress_percent: 100, assets_available: true });
    expect(p).not.toHaveProperty("manifest");
    const urls = await s.alice.action(api.productions.getPlaybackUrl, { id: a.id });
    expect(urls.audio_url).toContain("master.mp3");
    await expect(s.bob.action(api.productions.getPlaybackUrl, { id: a.id })).rejects.toThrow();
  });
});
