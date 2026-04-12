import { api } from '../../core/api/client'
import type { McpGatewayConfig, PersonaMcpConfig } from './types'

export const mcpApi = {
  // User remote gateways
  listGateways: () =>
    api.get<McpGatewayConfig[]>('/api/user/mcp/gateways'),

  createGateway: (data: { name: string; url: string; api_key?: string | null; enabled?: boolean }) =>
    api.post<McpGatewayConfig>('/api/user/mcp/gateways', data),

  updateGateway: (id: string, data: Partial<McpGatewayConfig>) =>
    api.patch<McpGatewayConfig>(`/api/user/mcp/gateways/${id}`, data),

  deleteGateway: (id: string) =>
    api.delete(`/api/user/mcp/gateways/${id}`),

  // Admin gateways
  listAdminGateways: () =>
    api.get<McpGatewayConfig[]>('/api/admin/mcp/gateways'),

  createAdminGateway: (data: { name: string; url: string; api_key?: string | null; enabled?: boolean }) =>
    api.post<McpGatewayConfig>('/api/admin/mcp/gateways', data),

  updateAdminGateway: (id: string, data: Partial<McpGatewayConfig>) =>
    api.patch<McpGatewayConfig>(`/api/admin/mcp/gateways/${id}`, data),

  deleteAdminGateway: (id: string) =>
    api.delete(`/api/admin/mcp/gateways/${id}`),

  // Persona MCP config
  updatePersonaMcp: (personaId: string, config: PersonaMcpConfig) =>
    api.patch(`/api/personas/${personaId}/mcp`, config),
}
