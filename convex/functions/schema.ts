import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

export const style = v.union(v.literal("cinematic_documentary"), v.literal("calm_explainer"));
export const activeStatus = v.union(v.literal("researching"), v.literal("writing"), v.literal("narrating"), v.literal("scoring"), v.literal("mixing"), v.literal("quality_check"));
export const status = v.union(v.literal("queued"), activeStatus, v.literal("completed"), v.literal("failed"));
export const manifest = v.object({
  title: v.string(), description: v.string(), duration_seconds: v.number(),
  audio_object_key: v.string(), cover_object_key: v.string(), mime_type: v.literal("audio/mpeg"),
});

export default defineSchema({
  productions: defineTable({
    owner: v.string(), prompt: v.string(), duration_minutes_requested: v.union(v.literal(5), v.literal(10), v.literal(15)), style,
    status, progress_percent: v.number(), stage_message: v.string(), created_at: v.number(), updated_at: v.number(),
    attempt_count: v.number(), worker_id: v.optional(v.string()), lease_hash: v.optional(v.string()), lease_expires_at: v.optional(v.number()),
    manifest: v.optional(manifest), completed_lease_hash: v.optional(v.string()),
    error_message: v.optional(v.string()), internal_error_code: v.optional(v.string()), internal_error_details: v.optional(v.string()),
  }).index("by_owner_created", ["owner", "created_at"]).index("by_status_created", ["status", "created_at"]).index("by_lease_expiry", ["lease_expires_at"]),
});
