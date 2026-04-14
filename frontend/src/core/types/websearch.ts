export interface WebSearchProvider {
  provider_id: string
  display_name: string
  is_configured: boolean
  last_test_status: 'untested' | 'valid' | 'failed' | null
  last_test_error: string | null
}

export interface WebSearchCredential {
  provider_id: string
  is_configured: boolean
  last_test_status: 'untested' | 'valid' | 'failed' | null
  last_test_error: string | null
  last_test_at: string | null
}

export interface SetWebSearchKeyRequest {
  api_key: string
}

export interface TestWebSearchResponse {
  valid: boolean
  error: string | null
}
