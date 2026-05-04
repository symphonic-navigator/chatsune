import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { meApi } from '../../../core/api/meApi'
import { useAuthStore } from '../../../core/store/authStore'
import { useAuth } from '../../../core/hooks/useAuth'
import { ApiError } from '../../../core/api/client'

const MAX_LENGTH = 2000
const LABEL = "block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-2 font-mono"

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'

export function AboutMeTab() {
  const user = useAuthStore((s) => s.user)
  const role = useAuthStore((s) => s.user?.role)
  const navigate = useNavigate()
  const { deleteAccount } = useAuth()

  // --- Display Name ---
  const [displayName, setDisplayName] = useState(user?.display_name ?? '')
  const [dnOriginal, setDnOriginal] = useState(user?.display_name ?? '')
  const [dnStatus, setDnStatus] = useState<SaveStatus>('idle')
  const dnTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // --- About Me text ---
  const [text, setText] = useState('')
  const [original, setOriginal] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle')
  const savedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // --- Danger zone: self-delete ---
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleteConfirmText, setDeleteConfirmText] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  useEffect(() => {
    return () => {
      if (savedTimerRef.current) clearTimeout(savedTimerRef.current)
      if (dnTimerRef.current) clearTimeout(dnTimerRef.current)
    }
  }, [])

  useEffect(() => {
    meApi.getAboutMe()
      .then((data) => {
        const value = data.about_me ?? ''
        setText(value)
        setOriginal(value)
      })
      .catch(() => setLoadError(true))
      .finally(() => setLoading(false))
  }, [])

  async function handleSaveDisplayName() {
    setDnStatus('saving')
    try {
      const updated = await meApi.updateDisplayName(displayName)
      setDnOriginal(updated.display_name)
      setDisplayName(updated.display_name)
      setDnStatus('saved')
      if (dnTimerRef.current) clearTimeout(dnTimerRef.current)
      dnTimerRef.current = setTimeout(() => setDnStatus('idle'), 2000)
    } catch {
      setDnStatus('error')
    }
  }

  async function handleSave() {
    setSaveStatus('saving')
    try {
      const data = await meApi.updateAboutMe(text || null)
      const value = data.about_me ?? ''
      setText(value)
      setOriginal(value)
      setSaveStatus('saved')
      if (savedTimerRef.current) clearTimeout(savedTimerRef.current)
      savedTimerRef.current = setTimeout(() => setSaveStatus('idle'), 2000)
    } catch {
      setSaveStatus('error')
    }
  }

  async function handleDeleteAccount() {
    if (!user) return
    setDeleting(true)
    setDeleteError(null)
    try {
      const { slug } = await deleteAccount(user.username)
      // `replace: true` so the browser back button doesn't try to return
      // to the now-unauthorised user modal.
      navigate(`/deletion-complete/${slug}`, { replace: true })
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 403) {
          setDeleteError(
            'Master admin accounts cannot self-delete. Transfer the role first.',
          )
        } else if (err.status === 400) {
          setDeleteError('Username did not match — please type it exactly.')
        } else {
          setDeleteError(err.message || 'Could not delete account — please try again.')
        }
      } else {
        setDeleteError('Could not delete account — please try again.')
      }
      setDeleting(false)
    }
  }

  const isDnDirty = displayName !== dnOriginal
  const isDirty = text !== original
  const isMasterAdmin = role === 'master_admin'
  const canConfirmDelete =
    !!user && deleteConfirmText === user.username && !deleting

  return (
    <div className="p-6 max-w-2xl flex flex-col gap-8 overflow-y-auto">

      {/* Display Name */}
      <div>
        <label
          htmlFor="display-name-input"
          className={LABEL}
        >
          Display Name
        </label>
        <div className="flex items-center gap-3">
          <input
            id="display-name-input"
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            maxLength={64}
            placeholder="Unnamed User"
            className="flex-1 bg-white/[0.03] border border-white/10 rounded-lg px-4 py-2 text-white/75 font-mono text-[13px] outline-none focus:border-gold/30 transition-colors"
          />
          <div className="flex items-center gap-2">
            {dnStatus === 'saved' && (
              <span className="font-mono text-[10px] text-white/40 tracking-wider uppercase">Saved</span>
            )}
            {dnStatus === 'error' && (
              <span className="font-mono text-[10px] text-red-400/80 tracking-wider uppercase">Failed</span>
            )}
            <button
              type="button"
              aria-label="Save display name"
              onClick={handleSaveDisplayName}
              disabled={dnStatus === 'saving' || !isDnDirty}
              className={[
                'font-mono text-[11px] uppercase tracking-[0.12em] px-5 py-2 rounded-lg transition-all border border-white/10',
                isDnDirty
                  ? 'bg-white/8 text-white/80 hover:bg-white/12 cursor-pointer'
                  : 'bg-transparent text-white/25 cursor-default',
              ].join(' ')}
            >
              {dnStatus === 'saving' ? 'Saving...' : 'Save'}
            </button>
          </div>
        </div>
      </div>

      {/* About Me text */}
      {loading ? (
        <div className="text-[12px] text-white/30 font-mono tracking-widest uppercase">Loading...</div>
      ) : loadError ? (
        <div className="text-[12px] text-red-400/70 font-mono">
          Could not load profile — please try again later.
        </div>
      ) : (
        <div>
          <label htmlFor="about-me-textarea" className={LABEL}>
            About You
          </label>
          <p className="text-[12px] text-white/40 font-mono mb-4 leading-relaxed">
            Tell your personas about yourself — your name, interests, preferences. Included at low
            priority in every conversation.
          </p>
          <textarea
            id="about-me-textarea"
            value={text}
            onChange={(e) => {
              if (e.target.value.length <= MAX_LENGTH) setText(e.target.value)
            }}
            placeholder="e.g. My name is Chris, I'm a developer living in Vienna..."
            className="w-full bg-white/[0.03] border border-white/10 rounded-lg px-4 py-3 text-white/75 font-mono text-[13px] leading-relaxed outline-none focus:border-gold/30 transition-colors resize-y"
            style={{ minHeight: 160 }}
          />
          <div className="flex items-center justify-between mt-3">
            <span className="font-mono text-[10px] text-white/25 tracking-wider">
              {text.length} / {MAX_LENGTH}
            </span>
            <div className="flex items-center gap-3">
              {saveStatus === 'saved' && (
                <span className="font-mono text-[10px] text-white/40 tracking-wider uppercase">Saved</span>
              )}
              {saveStatus === 'error' && (
                <span className="font-mono text-[10px] text-red-400/80 tracking-wider uppercase">Save failed</span>
              )}
              <button
                type="button"
                onClick={handleSave}
                disabled={saveStatus === 'saving' || !isDirty}
                className={[
                  'font-mono text-[11px] uppercase tracking-[0.12em] px-5 py-2 rounded-lg transition-all border border-white/10',
                  isDirty
                    ? 'bg-white/8 text-white/80 hover:bg-white/12 cursor-pointer'
                    : 'bg-transparent text-white/25 cursor-default',
                ].join(' ')}
              >
                {saveStatus === 'saving' ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Danger Zone — self-delete */}
      <div className="mt-8 pt-6 border-t border-white/8">
        <span className={LABEL}>Danger Zone</span>
        {isMasterAdmin ? (
          <p className="text-[12px] text-white/40 font-mono leading-relaxed">
            (master admin accounts cannot self-delete)
          </p>
        ) : (
          <>
            <p className="text-[12px] text-white/45 font-mono mb-4 leading-relaxed">
              Permanently delete your account and every piece of data we store
              about you. This cannot be undone.
            </p>
            {!confirmDelete ? (
              <button
                type="button"
                onClick={() => {
                  setConfirmDelete(true)
                  setDeleteError(null)
                  setDeleteConfirmText('')
                }}
                className="rounded-lg py-2 px-4 text-[12px] font-medium text-red-400/70 transition-colors hover:bg-red-400/8 hover:text-red-400/90"
                style={{ border: '1px solid rgba(248,113,113,0.18)' }}
              >
                Delete my account
              </button>
            ) : (
              <div
                className="rounded-lg p-4"
                style={{
                  border: '1px solid rgba(248,113,113,0.25)',
                  background: 'rgba(248,113,113,0.05)',
                }}
              >
                <p className="text-[12px] text-red-300/80 leading-relaxed mb-3">
                  This will permanently delete your account and every persona,
                  chat, memory, upload, artefact, knowledge library, LLM
                  connection, and setting you own. The data cannot be
                  recovered. Type your username{' '}
                  <strong className="text-red-200/90 font-mono">
                    {user?.username}
                  </strong>{' '}
                  to confirm.
                </p>
                <input
                  type="text"
                  value={deleteConfirmText}
                  onChange={(e) => setDeleteConfirmText(e.target.value)}
                  placeholder="your username"
                  autoComplete="off"
                  disabled={deleting}
                  className="w-full bg-black/20 border border-red-400/20 rounded-lg px-3 py-2 text-white/85 font-mono text-[13px] outline-none focus:border-red-400/50 transition-colors mb-3 disabled:opacity-50"
                />
                {deleteError && (
                  <p
                    role="alert"
                    className="text-[11px] text-red-300/90 font-mono mb-3 leading-relaxed"
                  >
                    {deleteError}
                  </p>
                )}
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={handleDeleteAccount}
                    disabled={!canConfirmDelete}
                    className="flex-1 rounded-lg py-2 text-[12px] font-medium text-white bg-red-500/80 hover:bg-red-500 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {deleting ? 'Deleting...' : 'Delete permanently'}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setConfirmDelete(false)
                      setDeleteConfirmText('')
                      setDeleteError(null)
                    }}
                    disabled={deleting}
                    className="px-4 rounded-lg py-2 text-[12px] text-white/55 hover:text-white/80 transition-colors disabled:opacity-50"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
