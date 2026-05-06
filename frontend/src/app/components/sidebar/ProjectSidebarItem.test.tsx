import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ProjectSidebarItem } from "./ProjectSidebarItem"
import type { ProjectDto } from "../../../features/projects/types"

vi.mock("../../../core/hooks/useViewport", () => ({
  useViewport: () => ({
    isDesktop: true, isMobile: false, isTablet: false, isLandscape: false,
    isSm: true, isMd: true, isLg: true, isXl: false,
  }),
}))

const mockProject: ProjectDto = {
  id: "proj-1",
  user_id: "user-1",
  title: "Star Trek Fan Fiction",
  emoji: "✨",
  description: "Fanfic with Mr. Worf about romulan diplomacy.",
  nsfw: false,
  pinned: true,
  sort_order: 0,
  knowledge_library_ids: [],
  system_prompt: null,
  created_at: "2026-05-01T12:00:00Z",
  updated_at: "2026-05-04T12:00:00Z",
}

const noop = () => {}

function renderItem(overrides: Partial<{
  project: ProjectDto
  onOpen: (id: string) => void
  onEdit: (id: string) => void
  onDelete: (id: string) => void
  onTogglePin: (id: string, pinned: boolean) => void
}> = {}) {
  return render(
    <ProjectSidebarItem
      project={overrides.project ?? mockProject}
      onOpen={overrides.onOpen ?? noop}
      onEdit={overrides.onEdit ?? noop}
      onDelete={overrides.onDelete ?? noop}
      onTogglePin={overrides.onTogglePin ?? noop}
    />,
  )
}

describe("ProjectSidebarItem — rendering", () => {
  it("renders the project title", () => {
    renderItem()
    expect(screen.getByText("Star Trek Fan Fiction")).toBeInTheDocument()
  })

  it("renders the project emoji when set", () => {
    renderItem()
    expect(screen.getByText("✨")).toBeInTheDocument()
  })

  it("falls back to a neutral dot when emoji is null", () => {
    const noEmoji: ProjectDto = { ...mockProject, emoji: null }
    const { container } = renderItem({ project: noEmoji })
    expect(screen.queryByText("✨")).not.toBeInTheDocument()
    expect(container.querySelectorAll("span.rounded-full").length).toBeGreaterThan(0)
  })

  it("falls back to 'Untitled project' when title is empty", () => {
    const blank: ProjectDto = { ...mockProject, title: "" }
    renderItem({ project: blank })
    expect(screen.getByText("Untitled project")).toBeInTheDocument()
  })

  it("calls onOpen when the row is clicked", async () => {
    const onOpen = vi.fn()
    renderItem({ onOpen })
    await userEvent.click(screen.getByText("Star Trek Fan Fiction"))
    expect(onOpen).toHaveBeenCalledWith("proj-1")
  })
})

describe("ProjectSidebarItem — context menu", () => {
  it("renders all four menu items when opened", async () => {
    renderItem()
    await userEvent.click(screen.getByLabelText("More options"))
    expect(screen.getByRole("menuitem", { name: "Unpin" })).toBeInTheDocument()
    expect(screen.getByRole("menuitem", { name: "Edit" })).toBeInTheDocument()
    expect(screen.getByRole("menuitem", { name: "Open" })).toBeInTheDocument()
    expect(screen.getByRole("menuitem", { name: "Delete" })).toBeInTheDocument()
  })

  it("shows 'Pin' label when project is unpinned", async () => {
    renderItem({ project: { ...mockProject, pinned: false } })
    await userEvent.click(screen.getByLabelText("More options"))
    expect(screen.getByRole("menuitem", { name: "Pin" })).toBeInTheDocument()
    expect(screen.queryByRole("menuitem", { name: "Unpin" })).not.toBeInTheDocument()
  })

  it("calls onTogglePin with the inverted flag when Pin/Unpin is clicked", async () => {
    const onTogglePin = vi.fn()
    renderItem({ onTogglePin })
    await userEvent.click(screen.getByLabelText("More options"))
    await userEvent.click(screen.getByRole("menuitem", { name: "Unpin" }))
    expect(onTogglePin).toHaveBeenCalledWith("proj-1", false)
  })

  it("calls onEdit when Edit is clicked", async () => {
    const onEdit = vi.fn()
    renderItem({ onEdit })
    await userEvent.click(screen.getByLabelText("More options"))
    await userEvent.click(screen.getByRole("menuitem", { name: "Edit" }))
    expect(onEdit).toHaveBeenCalledWith("proj-1")
  })

  it("calls onOpen when the menu Open item is clicked", async () => {
    const onOpen = vi.fn()
    renderItem({ onOpen })
    await userEvent.click(screen.getByLabelText("More options"))
    await userEvent.click(screen.getByRole("menuitem", { name: "Open" }))
    expect(onOpen).toHaveBeenCalledWith("proj-1")
  })

  it("calls onDelete when Delete is clicked", async () => {
    const onDelete = vi.fn()
    renderItem({ onDelete })
    await userEvent.click(screen.getByLabelText("More options"))
    await userEvent.click(screen.getByRole("menuitem", { name: "Delete" }))
    expect(onDelete).toHaveBeenCalledWith("proj-1")
  })

  it("opens via right-click on the row body", async () => {
    renderItem()
    const row = screen.getByText("Star Trek Fan Fiction").closest("div")!
    await userEvent.pointer({ keys: "[MouseRight]", target: row })
    expect(screen.getByRole("menuitem", { name: "Edit" })).toBeInTheDocument()
  })
})
