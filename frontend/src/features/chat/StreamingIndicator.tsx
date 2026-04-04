interface StreamingIndicatorProps { accentColour: string }

export function StreamingIndicator({ accentColour }: StreamingIndicatorProps) {
  return (
    <div className="flex items-center gap-1.5 py-2">
      {[0, 1, 2].map((i) => (
        <span key={i} className="inline-block h-2 w-2 rounded-full animate-think-pulse"
          style={{ backgroundColor: accentColour, animationDelay: `${i * 0.3}s` }} />
      ))}
    </div>
  )
}
