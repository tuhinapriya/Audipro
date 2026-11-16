// Bootstrap typed references; Convex codegen replaces these on deployment.
import { anyApi } from "convex/server";
import type { ApiFromModules, FilterApi, FunctionReference } from "convex/server";
import type * as productions from "../productions";
import type * as storage from "../storage";
import type * as worker from "../worker";
const fullApi = anyApi as unknown as ApiFromModules<{ productions: typeof productions; storage: typeof storage; worker: typeof worker }>;
export const api = fullApi as FilterApi<typeof fullApi, FunctionReference<any, "public">>;
export const internal = fullApi as FilterApi<typeof fullApi, FunctionReference<any, "internal">>;
