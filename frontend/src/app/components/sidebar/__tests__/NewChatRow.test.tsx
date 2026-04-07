import { render, screen, fireEvent } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { NewChatRow } from "../NewChatRow"
import type { PersonaDto } from "../../../../core/types/persona"

const mockNavigate = vi.fn()
vi.mock("react-router-dom", () => ({
  useNavigate: () => mockNavigate,
}))

const mockSanitised = { value: false }
vi.mock("../../../../core/store/sanitisedModeStore", () => ({
  useSanitisedMode: (sel: (s: { isSanitised: boolean }) => unknown) =>
    sel({ isSanitised: mockSanitised.value }),
}))

function p(id: string, name: string, opts: Partial<PersonaDto> = {}): PersonaDto {
  return {
    id,
    name,
    pinned: false,
    nsfw: false,
    ...opts,
  } as PersonaDto
}

describe("NewChatRow", () => {
  beforeEach(() => {
    mockNavigate.mockReset()
    mockSanitised.value = false
  })

  it("does not show the persona panel by default", () => {
    render(<NewChatRow personas={[p("a", "Alice")]} onCloseModal={() => {}} />)
    expect(screen.queryByText("Alice")).not.toBeInTheDocument()
  })

  it("expands to show personas (pinned first), navigates on click, and collapses", () => {
    const personas = [
      p("a", "Alice"),
      p("b", "Bob", { pinned: true }),
    ]
    render(<NewChatRow personas={personas} onCloseModal={() => {}} />)
    fireEvent.click(screen.getByRole("button", { name: /new chat/i }))

    const items = screen.getAllByTestId("new-chat-persona")
    expect(items.map((i) => i.textContent)).toEqual(["Bob", "Alice"])

    fireEvent.click(items[0])
    expect(mockNavigate).toHaveBeenCalledWith("/chat/b?new=1")
    expect(screen.queryByTestId("new-chat-persona")).not.toBeInTheDocument()
  })

  it("hides nsfw personas when sanitised mode is on", () => {
    mockSanitised.value = true
    render(
      <NewChatRow
        personas={[p("a", "Alice", { nsfw: true }), p("b", "Bob")]}
        onCloseModal={() => {}}
      />,
    )
    fireEvent.click(screen.getByRole("button", { name: /new chat/i }))
    expect(screen.queryByText("Alice")).not.toBeInTheDocument()
    expect(screen.getByText("Bob")).toBeInTheDocument()
  })

  it("shows an empty state when no personas are available", () => {
    render(<NewChatRow personas={[]} onCloseModal={() => {}} />)
    fireEvent.click(screen.getByRole("button", { name: /new chat/i }))
    expect(screen.getByText(/no personas available/i)).toBeInTheDocument()
  })
})
