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

export interface ArtefactListItem {
  id: string
  handle: string
  title: string
  type: ArtefactType
  language: string | null
  size_bytes: number
  version: number
  created_at: string
  updated_at: string
  session_id: string
  session_title: string | null
  persona_id: string
  persona_name: string
  persona_monogram: string
  persona_colour_scheme: string
}
