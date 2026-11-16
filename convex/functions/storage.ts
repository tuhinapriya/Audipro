"use node";
import { GetObjectCommand, HeadObjectCommand, S3Client } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";
import { v } from "convex/values";
import { internalAction } from "./_generated/server";

function storage() {
  const { R2_ACCOUNT_ID, R2_BUCKET, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY } = process.env;
  if (!R2_ACCOUNT_ID || !/^[a-f0-9]{32}$/i.test(R2_ACCOUNT_ID) || !R2_BUCKET || !R2_ACCESS_KEY_ID || !R2_SECRET_ACCESS_KEY) {
    throw new Error("R2 storage is not configured");
  }
  return { bucket: R2_BUCKET, client: new S3Client({ region: "auto", endpoint: `https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com`,
    credentials: { accessKeyId: R2_ACCESS_KEY_ID, secretAccessKey: R2_SECRET_ACCESS_KEY } }) };
}
export const verifyAssets = internalAction({
  args: { audio: v.string(), cover: v.string() },
  handler: async (_ctx, { audio, cover }) => {
    const { client, bucket } = storage();
    try {
      const objects = await Promise.all([audio, cover].map(Key => client.send(new HeadObjectCommand({ Bucket: bucket, Key }))));
      return objects.every(o => typeof o.ContentLength === "number" && o.ContentLength > 0);
    } catch (error) {
      const e = error as { name?: string; $metadata?: { httpStatusCode?: number } };
      if (e.name === "NotFound" || e.name === "NoSuchKey" || e.$metadata?.httpStatusCode === 404) return false;
      throw error;
    } finally { client.destroy(); }
  },
});
export const signPlayback = internalAction({
  args: { audio: v.string(), cover: v.string() },
  handler: async (_ctx, { audio, cover }) => {
    const { client, bucket } = storage();
    const signingDate = new Date();
    const expiresIn = 15 * 60;
    try {
      const [audio_url, cover_url] = await Promise.all([audio, cover].map(Key => getSignedUrl(client,
        new GetObjectCommand({ Bucket: bucket, Key }), { expiresIn, signingDate })));
      // Advertise a slightly earlier common expiry to allow for clock/network skew.
      return { audio_url, cover_url, expires_at: new Date(signingDate.getTime() + (expiresIn - 30) * 1000).toISOString() };
    } finally { client.destroy(); }
  },
});
