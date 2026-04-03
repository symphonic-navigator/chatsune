import { useState } from "react"
import { useUsers } from "../../core/hooks/useUsers"
import { useNotificationStore } from "../../core/store/notificationStore"
import type { CreateUserRequest, UpdateUserRequest, UserDto } from "../../core/types/auth"

function CreateUserForm({ onCreate }: { onCreate: (data: CreateUserRequest) => Promise<void> }) {
  const [username, setUsername] = useState("")
  const [email, setEmail] = useState("")
  const [displayName, setDisplayName] = useState("")
  const [role, setRole] = useState("user")
  const [result, setResult] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setResult(null)
    try {
      await onCreate({ username, email, display_name: displayName, role })
      setUsername("")
      setEmail("")
      setDisplayName("")
      setRole("user")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create user")
    }
  }

  return (
    <form onSubmit={handleSubmit} className="rounded-lg border border-gray-200 bg-white p-4 space-y-3">
      <h3 className="text-sm font-medium">Create User</h3>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {result && <p className="text-sm text-green-600">{result}</p>}
      <div className="grid grid-cols-2 gap-3">
        <input
          type="text" placeholder="Username" value={username}
          onChange={(e) => setUsername(e.target.value)} required
          className="rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
        />
        <input
          type="email" placeholder="Email" value={email}
          onChange={(e) => setEmail(e.target.value)} required
          className="rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
        />
        <input
          type="text" placeholder="Display Name" value={displayName}
          onChange={(e) => setDisplayName(e.target.value)} required
          className="rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
        />
        <select
          value={role} onChange={(e) => setRole(e.target.value)}
          className="rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
        >
          <option value="user">User</option>
          <option value="admin">Admin</option>
        </select>
      </div>
      <button type="submit" className="rounded bg-blue-600 px-4 py-1.5 text-sm text-white hover:bg-blue-700">
        Create
      </button>
    </form>
  )
}

function UserRow({
  user,
  onUpdate,
  onDeactivate,
  onResetPassword,
}: {
  user: UserDto
  onUpdate: (id: string, data: UpdateUserRequest) => Promise<unknown>
  onDeactivate: (id: string) => Promise<unknown>
  onResetPassword: (id: string) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [displayName, setDisplayName] = useState(user.display_name)
  const [email, setEmail] = useState(user.email)

  const handleSave = async () => {
    await onUpdate(user.id, { display_name: displayName, email })
    setEditing(false)
  }

  return (
    <tr className="border-b border-gray-100">
      <td className="px-4 py-2 text-sm">{user.username}</td>
      <td className="px-4 py-2 text-sm">
        {editing ? (
          <input
            value={displayName} onChange={(e) => setDisplayName(e.target.value)}
            className="rounded border border-gray-300 px-2 py-1 text-sm w-full"
          />
        ) : (
          user.display_name
        )}
      </td>
      <td className="px-4 py-2 text-sm">
        {editing ? (
          <input
            value={email} onChange={(e) => setEmail(e.target.value)}
            className="rounded border border-gray-300 px-2 py-1 text-sm w-full"
          />
        ) : (
          user.email
        )}
      </td>
      <td className="px-4 py-2 text-sm">
        <span className="rounded bg-gray-100 px-2 py-0.5 text-xs">{user.role}</span>
      </td>
      <td className="px-4 py-2 text-sm">
        <span className={`rounded px-2 py-0.5 text-xs ${user.is_active ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>
          {user.is_active ? "Active" : "Inactive"}
        </span>
      </td>
      <td className="px-4 py-2 text-sm space-x-1">
        {editing ? (
          <>
            <button onClick={handleSave} className="rounded bg-green-100 px-2 py-1 text-xs text-green-700 hover:bg-green-200">Save</button>
            <button onClick={() => setEditing(false)} className="rounded bg-gray-100 px-2 py-1 text-xs hover:bg-gray-200">Cancel</button>
          </>
        ) : (
          <>
            <button onClick={() => setEditing(true)} className="rounded bg-gray-100 px-2 py-1 text-xs hover:bg-gray-200">Edit</button>
            {user.is_active && user.role !== "master_admin" && (
              <button onClick={() => onDeactivate(user.id)} className="rounded bg-red-100 px-2 py-1 text-xs text-red-700 hover:bg-red-200">Deactivate</button>
            )}
            <button onClick={() => onResetPassword(user.id)} className="rounded bg-amber-100 px-2 py-1 text-xs text-amber-700 hover:bg-amber-200">Reset PW</button>
          </>
        )}
      </td>
    </tr>
  )
}

export default function UsersPage() {
  const { users, total, isLoading, error, create, update, deactivate, resetPassword } = useUsers()
  const addNotification = useNotificationStore((s) => s.addNotification)

  const handleCreate = async (data: CreateUserRequest) => {
    const res = await create(data)
    addNotification({
      level: "success",
      title: "User created",
      message: `Generated password: ${res.generated_password}`,
    })
  }

  const handleResetPassword = async (userId: string) => {
    const res = await resetPassword(userId)
    addNotification({
      level: "success",
      title: "Password reset",
      message: `New password: ${res.generated_password}`,
    })
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Users</h2>
        <span className="text-sm text-gray-400">{total} total</span>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <CreateUserForm onCreate={handleCreate} />

      <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-200 bg-gray-50">
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Username</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Display Name</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Email</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Role</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Status</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && users.length === 0 ? (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-sm text-gray-400">Loading...</td></tr>
            ) : users.length === 0 ? (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-sm text-gray-400">No users</td></tr>
            ) : (
              users.map((u) => (
                <UserRow key={u.id} user={u} onUpdate={update} onDeactivate={deactivate} onResetPassword={handleResetPassword} />
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
