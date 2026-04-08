interface InferenceWaitBannerProps {
  holderSource: string
}

function describeHolder(source: string): string {
  if (source.startsWith('job:memory_consolidation')) return 'memory consolidation'
  if (source.startsWith('job:memory_extraction')) return 'memory extraction'
  if (source.startsWith('job:title_generation')) return 'title generation'
  if (source.startsWith('job:')) return 'a background task'
  if (source === 'chat') return 'another chat inference'
  return 'a local inference task'
}

export function InferenceWaitBanner({ holderSource }: InferenceWaitBannerProps) {
  return (
    <div
      role="status"
      className="mx-4 my-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-200"
    >
      Waiting for {describeHolder(holderSource)} to finish — your message will
      start as soon as the local model is free.
    </div>
  )
}
