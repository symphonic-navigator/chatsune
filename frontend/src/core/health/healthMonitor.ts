import { apiUrl } from "../api/client"
import { useEventStore } from "../store/eventStore"

const BACKEND_MARKER_HEADER = "X-Chatsune-Backend"
const POLL_OK_MS = 5_000
const POLL_FAIL_MS = 1_000

let timer: ReturnType<typeof setTimeout> | null = null
let stopped = false

async function probe(): Promise<boolean> {
  try {
    const res = await fetch(apiUrl("/api/health"), { credentials: "include" })
    if (res.status !== 200) return false
    if (!res.headers.has(BACKEND_MARKER_HEADER)) return false
    return true
  } catch {
    return false
  }
}

async function tick(): Promise<void> {
  if (stopped) return
  // Skip while the tab is hidden — wakes back up via visibilitychange.
  if (typeof document !== "undefined" && document.hidden) {
    schedule(POLL_OK_MS)
    return
  }
  const ok = await probe()
  useEventStore.getState().setBackendAvailable(ok)
  schedule(ok ? POLL_OK_MS : POLL_FAIL_MS)
}

function schedule(delayMs: number): void {
  if (stopped) return
  timer = setTimeout(() => {
    void tick()
  }, delayMs)
}

function onVisibilityChange(): void {
  if (!document.hidden && !stopped) {
    if (timer) clearTimeout(timer)
    void tick()
  }
}

export function startHealthMonitor(): void {
  stopped = false
  if (typeof document !== "undefined") {
    document.addEventListener("visibilitychange", onVisibilityChange)
  }
  void tick()
}

export function stopHealthMonitor(): void {
  stopped = true
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
  if (typeof document !== "undefined") {
    document.removeEventListener("visibilitychange", onVisibilityChange)
  }
}

export async function probeNow(): Promise<void> {
  if (timer) clearTimeout(timer)
  await tick()
}
