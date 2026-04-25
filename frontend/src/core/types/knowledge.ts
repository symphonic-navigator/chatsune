export type RefreshFrequency = 'rarely' | 'standard' | 'often'

export interface KnowledgeLibraryDto {
  id: string
  name: string
  description: string | null
  nsfw: boolean
  document_count: number
  created_at: string
  updated_at: string
  default_refresh: RefreshFrequency
}

export interface KnowledgeDocumentDto {
  id: string
  library_id: string
  title: string
  media_type: 'text/markdown' | 'text/plain'
  size_bytes: number
  chunk_count: number
  embedding_status: 'pending' | 'processing' | 'completed' | 'failed'
  embedding_error: string | null
  created_at: string
  updated_at: string
  trigger_phrases: string[]
  refresh: RefreshFrequency | null
}

export interface KnowledgeDocumentDetailDto extends KnowledgeDocumentDto {
  content: string
}

export interface RetrievedChunkDto {
  library_name: string
  document_title: string
  heading_path: string[]
  preroll_text: string
  content: string
  score: number
}
