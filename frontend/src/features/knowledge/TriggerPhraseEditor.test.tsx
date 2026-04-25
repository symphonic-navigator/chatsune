import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { TriggerPhraseEditor } from "./TriggerPhraseEditor"

describe("TriggerPhraseEditor", () => {
  it("renders existing phrases as tags", () => {
    render(
      <TriggerPhraseEditor
        value={["andromedagalaxie", "sigma-sektor"]}
        onChange={() => {}}
      />,
    )
    expect(screen.getByText("andromedagalaxie")).toBeInTheDocument()
    expect(screen.getByText("sigma-sektor")).toBeInTheDocument()
  })

  it("shows normalisation preview while typing", () => {
    render(<TriggerPhraseEditor value={[]} onChange={() => {}} />)
    const input = screen.getByPlaceholderText(/add phrase/i) as HTMLInputElement
    fireEvent.change(input, { target: { value: "  Andromeda  Galaxie  " } })
    expect(screen.getByText(/will be saved as/i)).toHaveTextContent(
      "andromeda galaxie",
    )
  })

  it("adds normalised phrase on Enter", () => {
    const onChange = vi.fn()
    render(<TriggerPhraseEditor value={[]} onChange={onChange} />)
    const input = screen.getByPlaceholderText(/add phrase/i)
    fireEvent.change(input, { target: { value: "Andromedagalaxie" } })
    fireEvent.keyDown(input, { key: "Enter" })
    expect(onChange).toHaveBeenCalledWith(["andromedagalaxie"])
  })

  it("removes a phrase when × is clicked", () => {
    const onChange = vi.fn()
    render(<TriggerPhraseEditor value={["foo", "bar"]} onChange={onChange} />)
    const removeButtons = screen.getAllByRole("button", { name: /remove/i })
    fireEvent.click(removeButtons[0])
    expect(onChange).toHaveBeenCalledWith(["bar"])
  })

  it("does not add duplicate phrases", () => {
    const onChange = vi.fn()
    render(<TriggerPhraseEditor value={["foo"]} onChange={onChange} />)
    const input = screen.getByPlaceholderText(/add phrase/i)
    fireEvent.change(input, { target: { value: "FOO" } })
    fireEvent.keyDown(input, { key: "Enter" })
    // FOO normalises to foo → already present → onChange called with same array
    expect(onChange).toHaveBeenCalledWith(["foo"])
  })

  it("ignores empty input on Enter", () => {
    const onChange = vi.fn()
    render(<TriggerPhraseEditor value={["foo"]} onChange={onChange} />)
    const input = screen.getByPlaceholderText(/add phrase/i)
    fireEvent.change(input, { target: { value: "   " } })
    fireEvent.keyDown(input, { key: "Enter" })
    expect(onChange).not.toHaveBeenCalled()
  })
})
