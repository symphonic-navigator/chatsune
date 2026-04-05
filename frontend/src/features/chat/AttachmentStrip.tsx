import type { PendingAttachment } from '../../core/store/uploadStore'

interface AttachmentStripProps {
  attachments: PendingAttachment[]
  onRemove: (localId: string) => void
}

export function AttachmentStrip({ attachments, onRemove }: AttachmentStripProps) {
  if (attachments.length === 0) return null

  return (
    <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-thin">
      {attachments.map((att) => (
        <div key={att.localId} className="group relative flex-shrink-0">
          <div className="flex h-16 w-16 items-center justify-center overflow-hidden rounded-lg border border-white/10 bg-white/4">
            {att.status === 'uploading' && (
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-white/20 border-t-white/60" />
            )}
            {att.status === 'error' && (
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="text-red-400">
                <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.5" />
                <path d="M8 5V8.5M8 10.5V11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            )}
            {att.status === 'done' && _renderPreview(att)}
          </div>

          {/* Remove button */}
          <button
            type="button"
            onClick={() => onRemove(att.localId)}
            className="absolute -right-1 -top-1 hidden h-4 w-4 items-center justify-center rounded-full bg-white/15 text-white/60 transition-colors hover:bg-white/25 group-hover:flex"
          >
            <svg width="8" height="8" viewBox="0 0 8 8" fill="none">
              <path d="M1 1L7 7M7 1L1 7" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
            </svg>
          </button>

          {/* Filename label */}
          <div className="mt-0.5 max-w-[64px] truncate text-center text-[10px] text-white/30">
            {att.dto?.display_name ?? att.file.name}
          </div>
        </div>
      ))}
    </div>
  )
}

function _renderPreview(att: PendingAttachment) {
  const isImage = att.file.type.startsWith('image/') || att.dto?.media_type.startsWith('image/')

  if (isImage) {
    const src = att.localPreviewUrl
      ?? (att.dto?.thumbnail_b64 ? `data:image/jpeg;base64,${att.dto.thumbnail_b64}` : null)
    if (src) {
      return <img src={src} alt="" className="h-full w-full object-cover" />
    }
  }

  // Text/other file icon
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" className="text-white/30">
      <path d="M4 2H12L16 6V18H4V2Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
      <path d="M12 2V6H16" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
      <path d="M7 10H13M7 13H11" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  )
}
