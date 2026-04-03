import type { ReactNode } from "react"

interface NavRowProps {
  icon: ReactNode
  label: string
  onClick: () => void
  actions?: ReactNode
}

export function NavRow({ icon, label, onClick, actions }: NavRowProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 mx-1.5 my-0.5 cursor-pointer transition-colors hover:bg-white/6"
      style={{ width: "calc(100% - 12px)" }}
    >
      <span className="w-4 flex-shrink-0 text-center text-sm text-white/50">{icon}</span>
      <span className="flex-1 text-left text-[13px] font-semibold text-white/60 underline-offset-2 transition-colors group-hover:text-white/90 group-hover:underline">
        {label}
      </span>
      {actions && (
        <div
          className="flex gap-0.5"
          onClick={(e) => e.stopPropagation()}
        >
          {actions}
        </div>
      )}
    </button>
  )
}
