import { usePwaInstallStore } from "../../../core/pwa/installPrompt"

/**
 * Dezenter Install-Hinweis für die PWA.
 *
 * Shows a small floating banner inviting the user to add Chatsune to
 * their home screen. Deliberately unobtrusive: only appears when
 *   - the browser has actually fired `beforeinstallprompt`
 *   - the app is not already installed / running standalone
 *   - the user has not dismissed the hint before
 *   - this is at least the user's second visit
 *
 * iOS Safari never fires `beforeinstallprompt`, so the banner stays
 * hidden there — iOS users install via the native Share sheet.
 */
export function InstallHint() {
  const promptEvent = usePwaInstallStore((s) => s.promptEvent)
  const isInstalled = usePwaInstallStore((s) => s.isInstalled)
  const dismissed = usePwaInstallStore((s) => s.dismissed)
  const visitCount = usePwaInstallStore((s) => s.visitCount)
  const install = usePwaInstallStore((s) => s.install)
  const dismiss = usePwaInstallStore((s) => s.dismiss)

  if (isInstalled || dismissed || !promptEvent || visitCount < 2) {
    return null
  }

  return (
    <div
      className="pointer-events-auto fixed right-4 bottom-4 z-[55] flex max-w-xs items-center gap-3 rounded-lg px-4 py-3 shadow-lg lg:backdrop-blur-sm"
      style={{
        background: "rgba(124, 92, 191, 0.10)",
        border: "1px solid rgba(124, 92, 191, 0.30)",
      }}
      role="dialog"
      aria-label="App installieren"
    >
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-semibold text-white/90">
          App installieren
        </div>
        <div className="mt-0.5 text-[11px] text-white/50">
          Chatsune auf den Startbildschirm legen.
        </div>
      </div>
      <button
        className="flex-shrink-0 cursor-pointer rounded-md px-2.5 py-1 text-[11px] transition-colors"
        style={{
          color: "rgb(124, 92, 191)",
          background: "rgba(124, 92, 191, 0.18)",
          border: "1px solid rgba(124, 92, 191, 0.35)",
        }}
        onClick={() => {
          void install()
        }}
      >
        Installieren
      </button>
      <button
        className="flex-shrink-0 cursor-pointer text-sm text-white/30 transition-colors hover:text-white/60"
        onClick={dismiss}
        aria-label="Schliessen"
      >
        {"\u00D7"}
      </button>
    </div>
  )
}
