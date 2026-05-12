/**
 * API client for /api/chatgpt-import/*.
 *
 * Mirrors ``shared/dtos/chatgpt_import.py``. The upload endpoint uses
 * XMLHttpRequest instead of fetch so the UI can render upload-progress
 * indicators — ``fetch`` lacks ``upload.onprogress`` on most browsers.
 */
import { api, apiUrl, ApiError, currentAccessToken } from './client'

export interface ImportedInfoDto {
  persona_id: string
  persona_name: string
  session_id: string
  imported_at: string
}

export interface ImportDto {
  import_id: string
  filename: string
  file_size_bytes: number
  status: 'parsing' | 'ready' | 'failed'
  conversation_count: number
  skipped_count: number
  skipped_reasons: Record<string, number>
  created_at: string
  expires_at: string
  last_import_at: string | null
  error_message: string | null
}

export interface ConversationItemDto {
  chatgpt_conversation_id: string
  title: string
  create_time: string
  update_time: string
  message_count: number
  first_user_message_preview: string
  first_assistant_message_preview: string
  default_model_slug: string | null
  imports: ImportedInfoDto[]
}

export interface UploadResponse {
  import_id: string
  status: 'parsing' | 'ready' | 'failed'
  duplicate: boolean
}

export interface ImportTriggerResponse {
  correlation_id: string
  jobs: { chatgpt_conversation_id: string; job_id: string }[]
}

export interface UploadOptions {
  replace?: boolean
  onProgress?: (loaded: number, total: number | null) => void
  signal?: AbortSignal
}

function uploadViaXhr(
  file: File,
  options: UploadOptions,
): Promise<UploadResponse> {
  const url =
    apiUrl(`/api/chatgpt-import/uploads`) +
    `?filename=${encodeURIComponent(file.name)}` +
    (options.replace ? '&replace=true' : '')
  const token = currentAccessToken()

  return new Promise<UploadResponse>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', url)
    xhr.setRequestHeader('Content-Type', 'application/octet-stream')
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    xhr.withCredentials = true

    xhr.upload.onprogress = (e) => {
      options.onProgress?.(e.loaded, e.lengthComputable ? e.total : null)
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as UploadResponse)
        } catch (err) {
          reject(new ApiError(xhr.status, 'Malformed response', xhr.responseText))
        }
      } else {
        let body: unknown = null
        try {
          body = JSON.parse(xhr.responseText)
        } catch {
          /* fall through with the raw text body */
        }
        reject(new ApiError(xhr.status, xhr.statusText || 'Upload failed', body))
      }
    }
    xhr.onerror = () => reject(new ApiError(0, 'Network error', null))
    xhr.onabort = () => reject(new ApiError(0, 'Upload aborted', null))
    options.signal?.addEventListener('abort', () => xhr.abort())
    xhr.send(file)
  })
}

export const chatGptImportApi = {
  uploadFile: (file: File, options: UploadOptions = {}) =>
    uploadViaXhr(file, options),

  getActiveImport: () =>
    api.get<ImportDto | null>('/api/chatgpt-import/uploads/active'),

  deleteImport: (importId: string) =>
    api.delete<void>(`/api/chatgpt-import/uploads/${importId}`),

  listConversations: (
    importId: string,
    params: { titleSearch?: string; sort?: string } = {},
  ) => {
    const q = new URLSearchParams()
    if (params.titleSearch) q.set('title_search', params.titleSearch)
    if (params.sort) q.set('sort', params.sort)
    const query = q.toString()
    return api.get<ConversationItemDto[]>(
      `/api/chatgpt-import/uploads/${importId}/conversations${query ? `?${query}` : ''}`,
    )
  },

  triggerImport: (
    importId: string,
    body: { persona_id: string; chatgpt_conversation_ids: string[] },
  ) =>
    api.post<ImportTriggerResponse>(
      `/api/chatgpt-import/uploads/${importId}/import`,
      body,
    ),
}
