// Admin debug overlay — DTO contracts mirroring shared/dtos/debug.py.
//
// All fields are diagnostic snapshots. Treat them as best-effort: a job may
// transition between snapshot and render, a lock may be released between
// read and use. The admin overlay is observability, not authority.

export interface ActiveInferenceDto {
  inference_id: string
  user_id: string
  username: string | null
  connection_id: string
  connection_slug: string
  adapter_type: string
  model_slug: string
  model_unique_id: string
  source: string
  started_at: string
  duration_seconds: number
}

export type JobStatus = "queued" | "running" | "retry_pending"

export interface JobSnapshotDto {
  job_id: string
  job_type: string
  user_id: string
  username: string | null
  model_unique_id: string
  correlation_id: string
  created_at: string
  age_seconds: number
  attempt: number
  status: JobStatus
  next_retry_at: string | null
  max_retries: number | null
}

export type LockKind = "user" | "job"

export interface LockSnapshotDto {
  kind: LockKind
  user_id: string
  username: string | null
}

export interface StreamQueueDto {
  name: string
  stream_length: number
  pending_count: number
  oldest_pending_age_seconds: number | null
  consumer_group: string | null
}

export interface EmbeddingQueueDto {
  model_loaded: boolean
  model_name: string
  query_queue_size: number
  embed_queue_size: number
}

export interface DebugSnapshotDto {
  generated_at: string
  active_inferences: ActiveInferenceDto[]
  jobs: JobSnapshotDto[]
  locks: LockSnapshotDto[]
  stream_queues: StreamQueueDto[]
  embedding_queue: EmbeddingQueueDto
}
