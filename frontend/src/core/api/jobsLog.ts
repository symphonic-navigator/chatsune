import { api } from "./client"
import type { JobLogEntry } from "../types/jobLog"

export async function fetchJobLog(limit = 200): Promise<JobLogEntry[]> {
  const data = await api.get<{ entries: JobLogEntry[] }>(`/api/jobs/log?limit=${limit}`)
  return data.entries
}
