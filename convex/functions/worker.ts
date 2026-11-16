import { v } from "convex/values";
import { internalMutation, internalQuery } from "./_generated/server";
import type { MutationCtx, QueryCtx } from "./_generated/server";
import { activeStatus, manifest } from "./schema";

const LEASE_MS = 10 * 60_000;
const leaseArgs = { job_id: v.string(), lease_hash: v.string() };
const terminal = (s: string) => s === "completed" || s === "failed" || s === "queued";
async function load(ctx: Pick<QueryCtx, "db">, jobId: string) {
  const id = ctx.db.normalizeId("productions", jobId);
  return id ? await ctx.db.get(id) : null;
}
function leaseValid(p: NonNullable<Awaited<ReturnType<typeof load>>>, hash: string, now: number) {
  return !terminal(p.status) && p.lease_hash === hash && p.lease_expires_at !== undefined && p.lease_expires_at > now;
}
const notFound = { result: "not_found" as const };
const conflict = { result: "conflict" as const };

export const claim = internalMutation({
  args: { worker_id: v.string(), lease_hash: v.string() },
  handler: async (ctx, { worker_id, lease_hash }) => {
    const p = await ctx.db.query("productions").withIndex("by_status_created", q => q.eq("status", "queued")).first();
    if (!p) return null;
    const now = Date.now(), expires = now + LEASE_MS;
    await ctx.db.patch(p._id, { status: "researching", progress_percent: 0, stage_message: "Researching the subject",
      updated_at: now, worker_id, lease_hash, lease_expires_at: expires, attempt_count: p.attempt_count + 1 });
    return { job: { id: p._id, prompt: p.prompt, duration_minutes: p.duration_minutes_requested, style: p.style }, lease_expires_at: new Date(expires).toISOString() };
  },
});
export const progress = internalMutation({
  args: { ...leaseArgs, status: activeStatus, progress_percent: v.number(), stage_message: v.string() },
  handler: async (ctx, args) => {
    const p = await load(ctx, args.job_id);
    if (!p) return notFound;
    if (!leaseValid(p, args.lease_hash, Date.now()) || args.progress_percent < p.progress_percent) return conflict;
    await ctx.db.patch(p._id, { status: args.status, progress_percent: args.progress_percent, stage_message: args.stage_message, updated_at: Date.now() });
    return { result: "ok" as const };
  },
});
export const heartbeat = internalMutation({
  args: leaseArgs,
  handler: async (ctx, args) => {
    const p = await load(ctx, args.job_id);
    if (!p) return notFound;
    const now = Date.now();
    if (!leaseValid(p, args.lease_hash, now)) return conflict;
    await ctx.db.patch(p._id, { lease_expires_at: now + LEASE_MS, updated_at: now });
    return { result: "ok" as const };
  },
});
function sameManifest(a: NonNullable<NonNullable<Awaited<ReturnType<typeof load>>>["manifest"]>, b: typeof a) {
  return a.title === b.title && a.description === b.description && a.duration_seconds === b.duration_seconds &&
    a.audio_object_key === b.audio_object_key && a.cover_object_key === b.cover_object_key && a.mime_type === b.mime_type;
}
function completionState(p: NonNullable<Awaited<ReturnType<typeof load>>>, hash: string, value: NonNullable<typeof p.manifest>) {
  if (p.status === "completed") return p.completed_lease_hash === hash && p.manifest && sameManifest(p.manifest, value) ? "already" : "conflict";
  return leaseValid(p, hash, Date.now()) ? "ok" : "conflict";
}
export const checkComplete = internalQuery({
  args: { ...leaseArgs, manifest },
  handler: async (ctx, args) => {
    const p = await load(ctx, args.job_id);
    if (!p) return notFound;
    return { result: completionState(p, args.lease_hash, args.manifest) };
  },
});
export const complete = internalMutation({
  args: { ...leaseArgs, manifest },
  handler: async (ctx, args) => {
    const p = await load(ctx, args.job_id);
    if (!p) return notFound;
    const state = completionState(p, args.lease_hash, args.manifest);
    if (state !== "ok") return { result: state };
    await ctx.db.patch(p._id, { status: "completed", progress_percent: 100, stage_message: "Production complete", updated_at: Date.now(),
      manifest: args.manifest, completed_lease_hash: args.lease_hash, worker_id: undefined, lease_hash: undefined, lease_expires_at: undefined });
    return { result: "ok" as const };
  },
});
export const fail = internalMutation({
  args: { ...leaseArgs, error_code: v.string(), error_message: v.string() },
  handler: async (ctx, args) => {
    const p = await load(ctx, args.job_id);
    if (!p) return notFound;
    if (!leaseValid(p, args.lease_hash, Date.now())) return conflict;
    await ctx.db.patch(p._id, { status: "failed", stage_message: "Production failed", updated_at: Date.now(),
      error_message: "Production could not be completed. Please try again.", internal_error_code: args.error_code, internal_error_details: args.error_message,
      worker_id: undefined, lease_hash: undefined, lease_expires_at: undefined });
    return { result: "ok" as const };
  },
});
async function recover(ctx: MutationCtx, p: NonNullable<Awaited<ReturnType<typeof load>>>, now: number) {
  const requeue = p.attempt_count < 2;
  await ctx.db.patch(p._id, { status: requeue ? "queued" : "failed", progress_percent: requeue ? 0 : p.progress_percent,
    stage_message: requeue ? "In the production queue" : "Production failed", updated_at: now,
    error_message: requeue ? undefined : "Production timed out. Please try again.",
    internal_error_code: requeue ? undefined : "LEASE_EXPIRED", worker_id: undefined, lease_hash: undefined, lease_expires_at: undefined });
}
export const recoverExpired = internalMutation({
  args: {},
  handler: async ctx => {
    const now = Date.now();
    // Bounded batches; the next cron invocation continues draining the index.
    const expired = await ctx.db.query("productions").withIndex("by_lease_expiry", q => q.gte("lease_expires_at", 0).lte("lease_expires_at", now)).take(100);
    for (const p of expired) if (!terminal(p.status)) await recover(ctx, p, now);
    return expired.length;
  },
});
