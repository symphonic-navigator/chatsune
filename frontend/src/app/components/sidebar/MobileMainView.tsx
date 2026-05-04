import type { ReactNode } from 'react'
import { BookmarkIcon, CollegeIcon, LockClosedIcon, LockOpenIcon } from '../../../core/components/symbols'
import { PROJECTS_ENABLED } from '../../../core/config/featureGates'

interface MobileMainViewProps {
  isAdmin: boolean
  isInChat: boolean
  hasLastSession: boolean
  hasApiKeyProblem: boolean
  isSanitised: boolean
  avatarHighlight: boolean
  displayName: string
  role: string
  initial: string
  onAdmin: () => void
  onContinue: () => void
  onNewChat: () => void
  onPersonas: () => void
  onProjects: () => void
  onHistory: () => void
  onBookmarks: () => void
  onKnowledge: () => void
  onMyData: () => void
  onToggleSanitised: () => void
  onUserRow: () => void
  onOpenSettings: () => void
  onLogout: () => void
}

export function MobileMainView(props: MobileMainViewProps) {
  return (
    <div className="flex h-full flex-col">
      {/* Top section — mirrors desktop order: New Chat → Continue → Personas → History */}
      <div className="flex-shrink-0 pt-2">
        {props.isAdmin && (
          <>
            <button
              type="button"
              onClick={props.onAdmin}
              className="mx-3 flex w-[calc(100%-24px)] items-center gap-2 rounded-lg border border-gold/16 bg-gold/7 px-2.5 py-1.5 transition-colors hover:bg-gold/12"
            >
              <span className="text-[12px]">🪄</span>
              <span className="flex-1 text-left text-[12px] font-bold uppercase tracking-widest text-gold">
                Admin
              </span>
              <span className="text-[11px] text-gold/50">›</span>
            </button>
            <Divider />
          </>
        )}

        <NavRow icon="💬" label="New Chat" chev onClick={props.onNewChat} />

        {!props.isInChat && props.hasLastSession && (
          <NavRow icon="▶️" label="Continue" onClick={props.onContinue} />
        )}

        <Divider />

        <NavRow icon="💞" label="Personas" onClick={props.onPersonas} />
        {PROJECTS_ENABLED && (
          <NavRow icon="✨" label="Projects" chev onClick={props.onProjects} />
        )}
        <NavRow icon="📖" label="History" chev onClick={props.onHistory} />
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Bottom section — footer parity with desktop FooterBlock */}
      <div className="flex-shrink-0 border-t border-white/5">
        <NavRow icon={<CollegeIcon />} label="Knowledge" onClick={props.onKnowledge} />
        <NavRow icon={<BookmarkIcon />} label="Bookmarks" onClick={props.onBookmarks} />
        <NavRow icon="📂" label="My Data" onClick={props.onMyData} />

        <Divider />

        <button
          type="button"
          onClick={props.onToggleSanitised}
          aria-pressed={props.isSanitised}
          className="flex w-full items-center gap-3 px-3.5 py-2 text-left transition-colors hover:bg-white/4"
        >
          {props.isSanitised
            ? <LockClosedIcon style={{ fontSize: '15px' }} />
            : <LockOpenIcon className="opacity-60" style={{ fontSize: '15px' }} />}
          <span
            className={`flex-1 text-[13px] transition-colors ${
              props.isSanitised ? 'font-medium text-gold' : 'text-white/65'
            }`}
          >
            Sanitised
          </span>
        </button>

        <Divider />

        <div
          className={[
            'flex items-center gap-2.5 px-3 py-2 transition-colors',
            props.avatarHighlight ? 'bg-gold/7' : '',
          ].join(' ')}
        >
          <button
            type="button"
            onClick={props.onUserRow}
            className="flex flex-1 items-center gap-2.5 min-w-0 hover:opacity-80 transition-opacity"
            title="Your profile"
          >
            <div className="relative flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-purple to-gold text-[12px] font-bold text-white">
              {props.initial}
              {props.hasApiKeyProblem && (
                <span
                  aria-label="API key problem"
                  className="absolute -top-0.5 -right-0.5 flex h-3 w-3 items-center justify-center rounded-full bg-red-500 text-[7px] font-bold text-white"
                >
                  !
                </span>
              )}
            </div>
            <div className="min-w-0 flex-1 text-left">
              <p
                className={[
                  'truncate text-[13px] font-medium transition-colors',
                  props.avatarHighlight ? 'text-gold' : 'text-white/70',
                ].join(' ')}
              >
                {props.displayName}
              </p>
              <p className="text-[10px] text-white/55">{props.role}</p>
            </div>
          </button>

          <button
            type="button"
            onClick={props.onOpenSettings}
            title="Settings"
            aria-label="Settings"
            className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded text-[13px] text-white/60 transition-colors hover:bg-white/8 hover:text-white/85"
          >
            ···
          </button>
        </div>

        <button
          type="button"
          onClick={props.onLogout}
          className="flex w-full items-center gap-2 px-4 py-2 font-mono text-[11px] text-white/55 transition-colors hover:text-white/85"
        >
          <span>↪</span>
          <span>Log out</span>
        </button>
      </div>
    </div>
  )
}

interface NavRowProps {
  icon: ReactNode
  label: string
  chev?: boolean
  onClick: () => void
}

function NavRow({ icon, label, chev, onClick }: NavRowProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-3 px-3.5 py-2 text-left transition-colors hover:bg-white/4"
    >
      <span className="w-5 flex-shrink-0 text-center text-[15px]">{icon}</span>
      <span className="flex-1 text-[13px] text-white/70">{label}</span>
      {chev && <span className="text-[11px] text-white/30">›</span>}
    </button>
  )
}

function Divider() {
  return <div className="mx-3 my-1 h-px bg-white/6" />
}
