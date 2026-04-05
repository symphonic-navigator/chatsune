import type { AttachmentRefDto } from '../../core/api/storage'

interface AttachmentChipProps {
  attachment: AttachmentRefDto
}

export function AttachmentChip({ attachment }: AttachmentChipProps) {
  const isImage = attachment.media_type.startsWith('image/')

  return (
    <div className="inline-flex items-center gap-1.5 rounded-md border border-white/8 bg-white/4 px-2 py-1">
      {isImage && attachment.thumbnail_b64 ? (
        <img
          src={`data:image/jpeg;base64,${attachment.thumbnail_b64}`}
          alt={attachment.display_name}
          className="h-8 w-8 rounded object-cover"
        />
      ) : (
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="flex-shrink-0 text-white/30">
          <path d="M3 1H9L12 4V13H3V1Z" stroke="currentColor" strokeWidth="1" strokeLinejoin="round" />
          <path d="M9 1V4H12" stroke="currentColor" strokeWidth="1" strokeLinejoin="round" />
        </svg>
      )}
      <span className="max-w-[120px] truncate text-[11px] text-white/50">{attachment.display_name}</span>
      <span className="text-[10px] text-white/20">{_formatSize(attachment.size_bytes)}</span>
    </div>
  )
}

function _formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
