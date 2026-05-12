interface Props {
  conversationsIndexed: number
  failed?: { errorMessage: string } | null
  onRestart?: () => void
}

export function ParseProgressBanner({
  conversationsIndexed,
  failed,
  onRestart,
}: Props) {
  if (failed) {
    return (
      <div className="bg-red-900/30 border border-red-700 rounded-lg p-4 mb-4">
        <p className="text-red-200">Parsing failed: {failed.errorMessage}</p>
        {onRestart && (
          <button
            type="button"
            onClick={onRestart}
            className="mt-2 text-sm underline text-red-300 hover:text-red-100"
          >
            Start another upload
          </button>
        )}
      </div>
    )
  }
  return (
    <div className="bg-indigo-900/30 border border-indigo-700 rounded-lg p-4 mb-4 flex items-center gap-3">
      <span className="inline-block w-3 h-3 rounded-full bg-indigo-400 animate-pulse" />
      <p className="text-indigo-100">
        Processing file — <strong>{conversationsIndexed}</strong> conversations indexed…
      </p>
    </div>
  )
}
