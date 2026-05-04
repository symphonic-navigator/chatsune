import { NavRow } from './NavRow'
import { BookmarkIcon, CollegeIcon, LockClosedIcon, LockOpenIcon } from '../../../core/components/symbols'

interface FooterBlockProps {
  avatarTab: string
  avatarHighlight: boolean
  isSanitised: boolean
  displayName: string
  role: string
  initial: string
  hasApiKeyProblem: boolean
  isTabActive: (leaf: string) => boolean
  onOpenModal: (leaf: string) => void
  onOpenMyData: () => void
  onToggleSanitised: () => void
  onOpenUserRow: () => void
  onOpenSettings: () => void
  onLogout: () => void
}

/**
 * Sticky bottom of the sidebar: Knowledge / Bookmarks / My data,
 * Sanitised toggle, user identity row, Logout.
 */
export function FooterBlock({
  avatarHighlight,
  isSanitised,
  displayName,
  role,
  initial,
  hasApiKeyProblem,
  isTabActive,
  onOpenModal,
  onOpenMyData,
  onToggleSanitised,
  onOpenUserRow,
  onOpenSettings,
  onLogout,
}: FooterBlockProps) {
  return (
    <div className="flex-shrink-0 border-t border-white/5">
      <NavRow
        icon={<CollegeIcon />}
        label="Knowledge"
        isActive={isTabActive('knowledge')}
        onClick={() => onOpenModal('knowledge')}
      />
      <NavRow
        icon={<BookmarkIcon />}
        label="Bookmarks"
        isActive={isTabActive('bookmarks')}
        onClick={() => onOpenModal('bookmarks')}
      />
      <NavRow
        icon="📂"
        label="My data ›"
        isActive={isTabActive('uploads') || isTabActive('artefacts') || isTabActive('images')}
        onClick={onOpenMyData}
      />

      <div className="mx-2 my-1.5 h-px bg-white/4" />

      <button
        type="button"
        onClick={onToggleSanitised}
        title={isSanitised ? "Sanitised mode on — NSFW content hidden" : "Sanitised mode off — all content visible"}
        aria-label={isSanitised ? "Turn sanitised mode off" : "Turn sanitised mode on"}
        aria-pressed={isSanitised}
        className="flex w-full items-center gap-2.5 px-3.5 py-1.5 transition-colors hover:bg-white/5"
      >
        {isSanitised
          ? <LockClosedIcon style={{ fontSize: '15px' }} />
          : <LockOpenIcon className="opacity-60" style={{ fontSize: '15px' }} />}
        <span className={`text-[13px] transition-colors ${isSanitised ? "text-gold font-medium" : "text-white/60"}`}>
          Sanitised
        </span>
      </button>

      <div className="mx-2 my-1.5 h-px bg-white/4" />

      <div
        className={[
          "flex items-center gap-2.5 px-3 py-2 transition-colors",
          avatarHighlight ? "bg-gold/7" : "",
        ].join(" ")}
      >
        <button
          type="button"
          onClick={onOpenUserRow}
          className="flex flex-1 items-center gap-2.5 min-w-0 hover:opacity-80 transition-opacity"
          title="Your profile"
        >
          <div className="relative flex h-[30px] w-[30px] flex-shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-purple to-gold text-[12px] font-bold text-white">
            {initial}
            {hasApiKeyProblem && (
              <span className="absolute -top-0.5 -right-0.5 flex h-3 w-3 items-center justify-center rounded-full bg-red-500 text-[7px] font-bold text-white">!</span>
            )}
          </div>
          <div className="text-left min-w-0">
            <p className={[
              "text-[13px] font-medium truncate transition-colors",
              avatarHighlight ? "text-gold" : "text-white/65",
            ].join(" ")}>
              {displayName}
            </p>
            <p className="text-[10px] text-white/60">{role}</p>
          </div>
        </button>

        <button
          type="button"
          onClick={onOpenSettings}
          title="Settings"
          aria-label="Settings"
          className="flex h-[22px] w-[22px] flex-shrink-0 items-center justify-center rounded text-[11px] text-white/60 transition-colors hover:bg-white/8 hover:text-white/85"
        >
          ···
        </button>
      </div>

      <button
        type="button"
        onClick={onLogout}
        aria-label="Log out"
        className="flex w-full items-center gap-2 px-4 py-1.5 text-[11px] text-white/60 hover:text-white/85 transition-colors font-mono"
      >
        <span>↪</span>
        <span>Log out</span>
      </button>
    </div>
  )
}
