import { api } from "./client"
import type {
  UserDto,
  UsersListResponse,
  CreateUserRequest,
  CreateUserResponse,
  UpdateUserRequest,
  ResetPasswordResponse,
  AuditLogResponse,
} from "../types/auth"

export const usersApi = {
  list: (skip = 0, limit = 50) =>
    api.get<UsersListResponse>(`/api/admin/users?skip=${skip}&limit=${limit}`),

  get: (userId: string) =>
    api.get<UserDto>(`/api/admin/users/${userId}`),

  create: (data: CreateUserRequest) =>
    api.post<CreateUserResponse>("/api/admin/users", data),

  update: (userId: string, data: UpdateUserRequest) =>
    api.patch<UserDto>(`/api/admin/users/${userId}`, data),

  deactivate: (userId: string) =>
    api.delete<{ status: string }>(`/api/admin/users/${userId}`),

  resetPassword: (userId: string) =>
    api.post<ResetPasswordResponse>(`/api/admin/users/${userId}/reset-password`),

  auditLog: (params?: { skip?: number; limit?: number; action?: string; actor_id?: string }) => {
    const query = new URLSearchParams()
    if (params?.skip !== undefined) query.set("skip", String(params.skip))
    if (params?.limit !== undefined) query.set("limit", String(params.limit))
    if (params?.action) query.set("action", params.action)
    if (params?.actor_id) query.set("actor_id", params.actor_id)
    return api.get<AuditLogResponse>(`/api/admin/audit-log?${query}`)
  },
}
