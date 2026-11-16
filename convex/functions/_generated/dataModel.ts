// Schema-derived bootstrap type; Convex codegen replaces this on deployment.
import type { DataModelFromSchemaDefinition } from "convex/server";
import schema from "../schema";
export type DataModel = DataModelFromSchemaDefinition<typeof schema>;