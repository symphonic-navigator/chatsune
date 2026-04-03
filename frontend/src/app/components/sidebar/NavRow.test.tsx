import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { NavRow } from "./NavRow"

describe("NavRow", () => {
  it("renders the label", () => {
    render(<NavRow icon="◈" label="Chat" onClick={() => {}} />)
    expect(screen.getByText("Chat")).toBeDefined()
  })

  it("calls onClick when the row is clicked", async () => {
    const onClick = vi.fn()
    render(<NavRow icon="◈" label="Chat" onClick={onClick} />)
    await userEvent.click(screen.getByRole("button"))
    expect(onClick).toHaveBeenCalledOnce()
  })

  it("renders action elements when provided", () => {
    render(
      <NavRow
        icon="◈"
        label="History"
        onClick={() => {}}
        actions={<button data-testid="search-btn">🔍</button>}
      />,
    )
    expect(screen.getByTestId("search-btn")).toBeDefined()
  })

  it("does not trigger onClick when an action button is clicked", async () => {
    const onClick = vi.fn()
    const onSearch = vi.fn()
    render(
      <NavRow
        icon="◈"
        label="History"
        onClick={onClick}
        actions={<button onClick={onSearch}>🔍</button>}
      />,
    )
    await userEvent.click(screen.getByText("🔍"))
    expect(onSearch).toHaveBeenCalledOnce()
    expect(onClick).not.toHaveBeenCalled()
  })
})
