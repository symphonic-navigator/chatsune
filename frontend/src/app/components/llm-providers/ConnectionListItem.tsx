import type { Connection } from '../../../core/types/llm'

interface ConnectionListItemProps {
  connection: Connection
  onClick: () => void
}

const STATUS_STYLE: Record<string, string> = {
  valid: 'bg-green-500/15 text-green-300 border-green-500/30',
  failed: 'bg-red-500/15 text-red-300 border-red-500/30',
  untested: 'bg-white/5 text-white/40 border-white/15',
}

const STATUS_LABEL: Record<string, string> = {
  valid: 'OK',
  failed: 'Fehler',
  untested: 'ungetestet',
}

export function ConnectionListItem({ connection, onClick }: ConnectionListItemProps) {
  const status = connection.last_test_status ?? 'untested'
  const statusClass = STATUS_STYLE[status] ?? STATUS_STYLE.untested
  const statusLabel = STATUS_LABEL[status] ?? status

  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        className="flex w-full items-center justify-between gap-3 rounded px-3 py-2.5 text-left hover:bg-white/5 cursor-pointer"
      >
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium text-white/90">
              {connection.display_name}
            </span>
            <span className="font-mono text-[10px] uppercase tracking-wider text-white/40">
              {connection.adapter_type}
            </span>
          </div>
          <div className="mt-0.5 truncate font-mono text-[11px] text-white/40">
            {connection.slug}
          </div>
          {connection.last_test_error && status === 'failed' && (
            <div className="mt-1 truncate text-[11px] text-red-300/80" title={connection.last_test_error}>
              {connection.last_test_error}
            </div>
          )}
        </div>
        <span
          className={[
            'flex-shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-mono uppercase tracking-wider',
            statusClass,
          ].join(' ')}
        >
          {statusLabel}
        </span>
      </button>
    </li>
  )
}
