import type { Homelab } from './types'
import { HomelabCard } from './HomelabCard'

export function HomelabList({ homelabs }: { homelabs: Homelab[] }) {
  if (homelabs.length === 0) {
    return (
      <div className="rounded border border-dashed border-white/10 p-8 text-center text-[13px] text-white/50">
        No homelabs yet. Create one to start sharing compute.
      </div>
    )
  }
  return (
    <ul className="space-y-3">
      {homelabs.map((h) => (
        <li key={h.homelab_id}>
          <HomelabCard homelab={h} />
        </li>
      ))}
    </ul>
  )
}
