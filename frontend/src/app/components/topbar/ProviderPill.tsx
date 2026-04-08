import { useProviderStatusStore } from "../../../core/llm/providerStatusStore"

interface ProviderPillProps {
  provider: string
  label: string
}

/**
 * Generic provider reachability pill. Renders a green-dot pill matching the
 * existing LivePill styling, and only renders when the provider is reachable.
 * Used today for "Local Ollama"; new providers can opt in by adding another
 * `<ProviderPill provider="..." label="..." />` to the topbar.
 */
export function ProviderPill({ provider, label }: ProviderPillProps) {
  const available = useProviderStatusStore((s) => s.statuses[provider] ?? false)
  if (!available) return null
  return (
    <span className="flex items-center gap-1.5 rounded-full border border-white/7 bg-white/4 px-2.5 py-0.5 font-mono text-[11px] text-white/35">
      <span className="h-1.5 w-1.5 rounded-full bg-live" />
      {label}
    </span>
  )
}
