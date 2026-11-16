// Minimal bootstrap bindings; Convex codegen may replace these on deployment.
import { actionGeneric, httpActionGeneric, internalActionGeneric, internalMutationGeneric, internalQueryGeneric, mutationGeneric, queryGeneric } from "convex/server";
import type { ActionBuilder, HttpActionBuilder, MutationBuilder, QueryBuilder, DataModelFromSchemaDefinition, GenericMutationCtx, GenericQueryCtx } from "convex/server";
import schema from "../schema";
export type DataModel = DataModelFromSchemaDefinition<typeof schema>;
export type MutationCtx = GenericMutationCtx<DataModel>;
export type QueryCtx = GenericQueryCtx<DataModel>;
export const query: QueryBuilder<DataModel, "public"> = queryGeneric;
export const internalQuery: QueryBuilder<DataModel, "internal"> = internalQueryGeneric;
export const mutation: MutationBuilder<DataModel, "public"> = mutationGeneric;
export const internalMutation: MutationBuilder<DataModel, "internal"> = internalMutationGeneric;
export const action: ActionBuilder<DataModel, "public"> = actionGeneric;
export const internalAction: ActionBuilder<DataModel, "internal"> = internalActionGeneric;
export const httpAction: HttpActionBuilder = httpActionGeneric;
