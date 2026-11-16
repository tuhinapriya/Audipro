import type { AuthConfig } from "convex/server";

// An unconfigured deployment has no trusted identity provider, never a demo identity.
const domain = process.env.AUTH_ISSUER;
const applicationID = process.env.AUTH_AUDIENCE;
if (!!domain !== !!applicationID) throw new Error("Set both AUTH_ISSUER and AUTH_AUDIENCE");
export default { providers: domain && applicationID ? [{ domain, applicationID }] : [] } satisfies AuthConfig;
