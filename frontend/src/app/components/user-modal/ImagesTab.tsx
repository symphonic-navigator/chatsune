// Images tab — wraps the existing `GalleryGrid` so it can accept a
// ``projectFilter`` prop and share the same shape as the other
// "user-modal" tabs (HistoryTab, UploadsTab, ArtefactsTab). Originally
// ``UserModal.tsx`` mounted ``GalleryGrid`` inline; the wrapper exists
// from Phase 9 onwards so the Project-Detail-Overlay can mount the
// same component as a tab.
//
// The actual filtering is wired in Task 37; the shell-only commit
// accepts the prop but the gallery still renders the unfiltered list.

import { GalleryGrid } from '../../../features/images/gallery/GalleryGrid'

interface ImagesTabProps {
  /**
   * Mindspace: when set, the tab scopes to a single project's
   * generated images. Phase 9 / spec §6.5 Tab 6.
   */
  projectFilter?: string
}

export function ImagesTab({ projectFilter: _projectFilter }: ImagesTabProps = {}) {
  return (
    <div className="flex-1 overflow-y-auto [&::-webkit-scrollbar]:w-[3px] [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/10">
      <GalleryGrid />
    </div>
  )
}
