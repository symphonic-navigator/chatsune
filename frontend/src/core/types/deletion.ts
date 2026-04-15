/**
 * Mirrors `shared/dtos/deletion.py` — keep field names in sync.
 *
 * Returned by the persona and knowledge-library DELETE handlers so the
 * frontend can show a transparent, scrollable "what was purged" report
 * after a destructive action.
 */

export interface DeletionStepDto {
  label: string
  deleted_count: number
  warnings: string[]
}

export interface DeletionReportDto {
  target_type: 'persona' | 'knowledge_library'
  target_id: string
  target_name: string
  success: boolean
  steps: DeletionStepDto[]
  timestamp: string
}
