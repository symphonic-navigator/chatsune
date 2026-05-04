// Mindspace projectFilter wiring for ImagesTab. The filtered branch
// uses a small in-tab gallery (no lightbox / pagination) so we only
// verify the API call shape and the rendered tile count.

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { GeneratedImageSummaryDto } from '@/core/api/images'

const listImagesMock = vi.fn(
  async (
    _opts?: { limit?: number; before?: string; project_id?: string },
  ): Promise<GeneratedImageSummaryDto[]> => [],
)
vi.mock('../../../../features/images/api', () => ({
  imagesApi: {
    listImages: (opts?: {
      limit?: number
      before?: string
      project_id?: string
    }) => listImagesMock(opts),
  },
}))

// Stub the global gallery so the unfiltered branch doesn't pull in
// the images store + lightbox dependencies.
vi.mock('../../../../features/images/gallery/GalleryGrid', () => ({
  GalleryGrid: () => <div data-testid="global-gallery">global gallery</div>,
}))

beforeEach(() => {
  vi.clearAllMocks()
  listImagesMock.mockReset()
})

describe('ImagesTab — projectFilter', () => {
  it('mounts the global gallery when no filter is provided', async () => {
    const { ImagesTab } = await import('../ImagesTab')
    render(<ImagesTab />)
    expect(screen.getByTestId('global-gallery')).toBeInTheDocument()
    expect(listImagesMock).not.toHaveBeenCalled()
  })

  it('fetches a project-scoped list when projectFilter is set', async () => {
    listImagesMock.mockResolvedValue([
      {
        id: 'img1',
        prompt: 'A starship',
        thumbnail_b64: null,
        thumb_url: '/thumbs/img1',
        generated_at: '2026-05-01T00:00:00Z',
      } as unknown as GeneratedImageSummaryDto,
    ])
    const { ImagesTab } = await import('../ImagesTab')
    render(<ImagesTab projectFilter="proj-trek" />)
    await Promise.resolve()
    await Promise.resolve()
    expect(listImagesMock).toHaveBeenCalledWith({
      project_id: 'proj-trek',
      limit: 200,
    })
    expect(await screen.findByTestId('project-image-img1')).toBeInTheDocument()
  })
})
