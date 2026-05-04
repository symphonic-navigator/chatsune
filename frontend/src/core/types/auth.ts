export interface UserDto {
  id: string
  username: string
  email: string
  display_name: string
  role: "user" | "admin" | "master_admin"
  is_active: boolean
  must_change_password: boolean
  created_at: string
  updated_at: string
  recent_emojis: string[]
  // Mindspace: dedicated LRU for the project-create / project-edit emoji
  // picker. Optional because legacy users predating Mindspace lack the
  // field on their document — defaults to ``[]`` server-side.
  recent_project_emojis?: string[]
}

export interface LoginRequest {
  username: string
  password: string
}

export interface SetupRequest {
  pin: string
  username: string
  email: string
  password: string
  display_name?: string
}

export interface ChangePasswordRequest {
  current_password: string
  new_password: string
}

export interface TokenResponse {
  access_token: string
  token_type: "bearer"
  expires_in: number
}

export interface SetupResponse {
  user: UserDto
  access_token: string
  token_type: "bearer"
  expires_in: number
}

export interface CreateUserRequest {
  username: string
  email: string
  display_name: string
  role?: string
}

export interface UpdateUserRequest {
  display_name?: string
  email?: string
  is_active?: boolean
  role?: string
}

export interface CreateUserResponse {
  user: UserDto
  generated_password: string
}

export interface ResetPasswordResponse {
  status: "reset"
  user: UserDto
}

export interface UsersListResponse {
  users: UserDto[]
  total: number
  skip: number
  limit: number
}

export interface AuditLogEntryDto {
  id: string
  timestamp: string
  actor_id: string
  action: string
  resource_type: string
  resource_id: string | null
  detail: Record<string, unknown> | null
}

export interface AuditLogResponse {
  entries: AuditLogEntryDto[]
  skip: number
  limit: number
}
