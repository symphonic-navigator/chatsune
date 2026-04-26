import { useEffect, useState } from 'react'
import { storageApi, type StorageFileDto } from '../../core/api/storage'
import type { GeneratedImageSummaryDto } from '../../core/api/images'
import { GeneratedImagesTab } from '../images/attachments/GeneratedImagesTab'

type ActiveTab = 'uploads' | 'generated'

interface UploadBrowserPanelProps {
  personaId?: string
  onSelect: (file: StorageFileDto) => void
  onSelectImage: (image: GeneratedImageSummaryDto) => void
  onClose: () => void
}

export function UploadBrowserPanel({
  personaId,
  onSelect,
  onSelectImage,
  onClose,
}: UploadBrowserPanelProps) {
  const [files, setFiles] = useState<StorageFileDto[]>([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<ActiveTab>('uploads')
  const isIncognito = !personaId

  useEffect(() => {
    if (isIncognito || activeTab !== 'uploads') return
    setLoading(true)
    storageApi
      .listFiles({ persona_id: personaId, sort_by: 'date', order: 'desc', limit: 50 })
      .then(setFiles)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [personaId, isIncognito, activeTab])

  return (
    <div className="border-t border-white/6 bg-surface px-4 py-3">
      <div className="mx-auto max-w-3xl">
        {/* Panel header with title and close button */}
        <div className="mb-2 flex items-center justify-between">
          <span className="text-[12px] font-medium text-white/40">Attach</span>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-0.5 text-white/30 transition-colors hover:text-white/50"
            aria-label="Close attachment picker"
          >
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
              <path d="M2 2L10 10M10 2L2 10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* Tab strip */}
        <div className="mb-2 flex gap-1 border-b border-white/6 pb-0">
          <TabButton
            active={activeTab === 'uploads'}
            onClick={() => setActiveTab('uploads')}
          >
            Uploads
          </TabButton>
          <TabButton
            active={activeTab === 'generated'}
            onClick={() => setActiveTab('generated')}
          >
            Generated Images
          </TabButton>
        </div>

        {/* Tab content */}
        {activeTab === 'uploads' && (
          <UploadsContent
            isIncognito={isIncognito}
            loading={loading}
            files={files}
            onSelect={onSelect}
          />
        )}
        {activeTab === 'generated' && (
          <GeneratedImagesTab onPick={onSelectImage} />
        )}
      </div>
    </div>
  )
}

// ---- sub-components ----------------------------------------------------------

interface TabButtonProps {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}

function TabButton({ active, onClick, children }: TabButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        'px-3 py-1.5 text-[11px] font-medium rounded-t-md transition-colors border-b-2 -mb-px',
        active
          ? 'text-white/80 border-white/40 bg-white/4'
          : 'text-white/35 border-transparent hover:text-white/55 hover:bg-white/4',
      ].join(' ')}
    >
      {children}
    </button>
  )
}

interface UploadsContentProps {
  isIncognito: boolean
  loading: boolean
  files: StorageFileDto[]
  onSelect: (file: StorageFileDto) => void
}

function UploadsContent({ isIncognito, loading, files, onSelect }: UploadsContentProps) {
  if (isIncognito) {
    return (
      <div className="py-4 text-center text-[12px] text-white/20">
        Upload browser is not available in incognito mode
      </div>
    )
  }
  if (loading) {
    return <div className="py-4 text-center text-[12px] text-white/20">Loading...</div>
  }
  if (files.length === 0) {
    return <div className="py-4 text-center text-[12px] text-white/20">No uploads yet</div>
  }
  return (
    <div className="flex max-h-[160px] gap-2 overflow-x-auto pb-1 scrollbar-thin">
      {files.map((f) => (
        <button
          key={f.id}
          type="button"
          onClick={() => onSelect(f)}
          className="group flex flex-shrink-0 flex-col items-center gap-0.5 rounded-lg p-1.5 transition-colors hover:bg-white/6"
        >
          <div className="flex h-12 w-12 items-center justify-center overflow-hidden rounded border border-white/8 bg-white/4">
            {f.thumbnail_b64 ? (
              <img src={`data:image/jpeg;base64,${f.thumbnail_b64}`} alt="" className="h-full w-full object-cover" />
            ) : (
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="text-white/25">
                <path d="M3 1H10L13 4V15H3V1Z" stroke="currentColor" strokeWidth="1" strokeLinejoin="round" />
                <path d="M10 1V4H13" stroke="currentColor" strokeWidth="1" strokeLinejoin="round" />
              </svg>
            )}
          </div>
          <span className="max-w-[56px] truncate text-[10px] text-white/30 group-hover:text-white/50">
            {f.display_name}
          </span>
        </button>
      ))}
    </div>
  )
}
