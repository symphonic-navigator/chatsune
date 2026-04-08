import { api } from "./client"
import type { DebugSnapshotDto } from "../types/debug"

export const debugApi = {
  /** Fetch a fresh diagnostic snapshot. Admin only. */
  snapshot: () => api.get<DebugSnapshotDto>("/api/admin/debug/snapshot"),
}
