export interface McpServerConfig {
  server_name: string
  prefix_enabled: boolean
  custom_prefix: string | null
  hidden: boolean
}

export interface McpToolOverride {
  original_name: string
  server_name: string
  display_name: string | null
  hidden: boolean
}

export interface McpGatewayConfig {
  id: string
  name: string
  url: string
  api_key: string | null
  enabled: boolean
  disabled_tools: string[]
  server_configs: Record<string, McpServerConfig>
  tool_overrides: McpToolOverride[]
}

export interface McpToolDefinition {
  name: string
  description: string
  inputSchema: Record<string, unknown>
  _gateway_server?: string
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

export interface PersonaMcpConfig {
  excluded_gateways: string[]
  excluded_servers: string[]
  excluded_tools: string[]
}

export interface McpSessionToolEntry {
  name: string
  description: string
  server_name: string
}

export interface McpSessionGateway {
  namespace: string
  tier: 'admin' | 'remote' | 'local'
  tools: McpSessionToolEntry[]
  collisions: string[]
}
