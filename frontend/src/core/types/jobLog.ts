export type JobLogStatus = 'started' | 'completed' | 'failed' | 'retry'

export interface JobLogEntry {
  entry_id: string
  job_id: string
  job_type: string
  persona_id: string | null
  status: JobLogStatus
  attempt: number
  silent: boolean
  ts: string // ISO timestamp
  duration_ms: number | null
  error_message: string | null
}
