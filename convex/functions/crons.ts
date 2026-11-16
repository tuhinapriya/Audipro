import { cronJobs } from "convex/server";
import { internal } from "./_generated/api";
const crons = cronJobs();
crons.interval("recover expired production leases", { minutes: 1 }, internal.worker.recoverExpired, {});
export default crons;
