export interface McpGatewayConfig {
  id: string
  name: string
  url: string
  api_key: string | null
  enabled: boolean
  disabled_tools: string[]
}

export interface McpToolDefinition {
  name: string
  description: string
  inputSchema: Record<string, unknown>
}

export interface McpGatewayStatus {
  id: string
  name: string
  tier: 'admin' | 'remote' | 'local'
  tool_count: number
  reachable: boolean
}

export interface McpToolsListResponse {
  tools: McpToolDefinition[]
  _errors?: Array<{ server: string; error: string }>
}

export interface McpToolCallResult {
  content: Array<{ type: string; text?: string }>
  isError?: boolean
}
