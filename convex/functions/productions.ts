import { v } from "convex/values";
import { action, internalQuery, mutation, query } from "./_generated/server";
import { internal } from "./_generated/api";
import { style } from "./schema";
import type { QueryCtx } from "./_generated/server";
import type { DataModel } from "./_generated/dataModel";
import type { DocumentByName } from "convex/server";

type Production = DocumentByName<DataModel, "productions">;
async function owner(ctx: Pick<QueryCtx, "auth">): Promise<string> {
  const identity = await ctx.auth.getUserIdentity();
  if (!identity) throw new Error("Authentication required");
  return identity.tokenIdentifier;
}
function summary(p: Production) {
  return {
    id: p._id, status: p.status, progress_percent: p.progress_percent, stage_message: p.stage_message,
    created_at: new Date(p.created_at).toISOString(), updated_at: new Date(p.updated_at).toISOString(),
    prompt: p.prompt, duration_minutes_requested: p.duration_minutes_requested, style: p.style,
    title: p.manifest?.title ?? null, description: p.manifest?.description ?? null,
    duration_seconds: p.manifest?.duration_seconds ?? null, assets_available: p.status === "completed" && !!p.manifest,
    error_message: p.error_message ?? null,
  };
}

export const create = mutation({
  args: { prompt: v.string(), duration_minutes: v.optional(v.number()), style: v.optional(style) },
  handler: async (ctx, args) => {
    const user = await owner(ctx);
    const prompt = args.prompt.trim();
    if (prompt.length < 10 || prompt.length > 2000) throw new Error("Prompt must contain 10–2000 characters");
    const duration = args.duration_minutes ?? 1;
    if (!Number.isFinite(duration) || duration < 1 / 6) throw new Error("Duration must be at least 10 seconds");
    const now = Date.now();
    const id = await ctx.db.insert("productions", { owner: user, prompt, duration_minutes_requested: duration,
      style: args.style ?? "cinematic_documentary", status: "queued", progress_percent: 0, stage_message: "In the production queue",
      created_at: now, updated_at: now, attempt_count: 0 });
    return { id, status: "queued" as const };
  },
});

export const get = query({
  args: { id: v.string() },
  handler: async (ctx, { id }) => {
    const user = await owner(ctx);
    const normalized = ctx.db.normalizeId("productions", id);
    const p = normalized ? await ctx.db.get(normalized) : null;
    return p && p.owner === user ? summary(p) : null;
  },
});
export const list = query({
  args: { limit: v.optional(v.number()) },
  handler: async (ctx, { limit }) => {
    const user = await owner(ctx);
    const n = limit ?? 20;
    if (!Number.isInteger(n) || n < 1 || n > 100) throw new Error("Limit must be an integer from 1 to 100");
    const rows = await ctx.db.query("productions").withIndex("by_owner_created", q => q.eq("owner", user)).order("desc").take(n);
    return rows.map(summary);
  },
});

// Auth is propagated by Convex from the action to this internal query.
export const playbackKeys = internalQuery({
  args: { id: v.string() },
  handler: async (ctx, { id }) => {
    const user = await owner(ctx);
    const normalized = ctx.db.normalizeId("productions", id);
    const p = normalized ? await ctx.db.get(normalized) : null;
    if (!p || p.owner !== user || p.status !== "completed" || !p.manifest) throw new Error("Production unavailable");
    return { audio: p.manifest.audio_object_key, cover: p.manifest.cover_object_key };
  },
});
export const getPlaybackUrl = action({
  args: { id: v.string() },
  handler: async (ctx, { id }): Promise<{ audio_url: string; cover_url: string; expires_at: string }> => {
    const keys: { audio: string; cover: string } = await ctx.runQuery(internal.productions.playbackKeys, { id });
    return await ctx.runAction(internal.storage.signPlayback, keys);
  },
});

export const retry = mutation({
  args: { id: v.string() },
  handler: async (ctx, { id }) => {
    const user = await owner(ctx);
    const normalized = ctx.db.normalizeId("productions", id);
    const p = normalized ? await ctx.db.get(normalized) : null;
    if (!p || p.owner !== user || p.status !== "failed") throw new Error("Production unavailable or not failed");
    await ctx.db.patch(p._id, { status: "queued", progress_percent: 0, stage_message: "In the production queue", updated_at: Date.now(),
      attempt_count: 0, worker_id: undefined, lease_hash: undefined, lease_expires_at: undefined, manifest: undefined,
      completed_lease_hash: undefined, error_message: undefined, internal_error_code: undefined, internal_error_details: undefined });
    return { id: p._id, status: "queued" as const };
  },
});
