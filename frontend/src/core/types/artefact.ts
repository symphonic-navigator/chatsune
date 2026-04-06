export type ArtefactType = 'markdown' | 'code' | 'html' | 'svg' | 'jsx' | 'mermaid'

export interface ArtefactSummary {
  id: string
  session_id: string
  handle: string
  title: string
  type: ArtefactType
  language: string | null
  size_bytes: number
  version: number
  created_at: string
  updated_at: string
}

export interface ArtefactDetail extends ArtefactSummary {
  content: string
  max_version: number
}
