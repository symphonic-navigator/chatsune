import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ProjectSidebarItem } from "./ProjectSidebarItem"
import type { ProjectDto } from "../../../features/projects/types"

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
  created_at: "2026-05-01T12:00:00Z",
  updated_at: "2026-05-04T12:00:00Z",
}

describe("ProjectSidebarItem", () => {
  it("renders the project title", () => {
    render(<ProjectSidebarItem project={mockProject} onOpen={() => {}} />)
    expect(screen.getByText("Star Trek Fan Fiction")).toBeInTheDocument()
  })

  it("renders the project emoji when set", () => {
    render(<ProjectSidebarItem project={mockProject} onOpen={() => {}} />)
    expect(screen.getByText("✨")).toBeInTheDocument()
  })

  it("falls back to a neutral dot when emoji is null", () => {
    const noEmoji: ProjectDto = { ...mockProject, emoji: null }
    const { container } = render(
      <ProjectSidebarItem project={noEmoji} onOpen={() => {}} />,
    )
    expect(screen.queryByText("✨")).not.toBeInTheDocument()
    expect(container.querySelectorAll("span.rounded-full").length).toBeGreaterThan(0)
  })

  it("falls back to 'Untitled project' when title is empty", () => {
    const blank: ProjectDto = { ...mockProject, title: "" }
    render(<ProjectSidebarItem project={blank} onOpen={() => {}} />)
    expect(screen.getByText("Untitled project")).toBeInTheDocument()
  })

  it("calls onOpen when the row is clicked", async () => {
    const onOpen = vi.fn()
    render(<ProjectSidebarItem project={mockProject} onOpen={onOpen} />)
    await userEvent.click(screen.getByText("Star Trek Fan Fiction"))
    expect(onOpen).toHaveBeenCalledWith("proj-1")
  })
})
