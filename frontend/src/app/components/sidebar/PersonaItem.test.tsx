import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { PersonaItem } from "./PersonaItem"
import type { PersonaDto } from "../../../core/types/persona"

const mockPersona: PersonaDto = {
  id: "p1",
  user_id: "u1",
  name: "Lyra",
  tagline: "Test persona",
  model_unique_id: "test:model",
  system_prompt: "",
  temperature: 0.8,
  reasoning_enabled: false,
  soft_cot_enabled: false,
  vision_fallback_model: null,
  nsfw: false,
  colour_scheme: "heart",
  display_order: 0,
  monogram: "L",
  pinned: false,
  profile_image: null,
  profile_crop: null,
  created_at: "2026-01-01",
  updated_at: "2026-01-01",
}

const noop = () => {}

describe("PersonaItem", () => {
  it("renders persona name", () => {
    render(
      <PersonaItem persona={mockPersona} isActive={false}
        onSelect={noop} onNewChat={noop} onNewIncognitoChat={noop}
        onEdit={noop} onUnpin={noop} />
    )
    expect(screen.getByText("Lyra")).toBeDefined()
  })

  it("renders avatar initial", () => {
    render(
      <PersonaItem persona={mockPersona} isActive={false}
        onSelect={noop} onNewChat={noop} onNewIncognitoChat={noop}
        onEdit={noop} onUnpin={noop} />
    )
    expect(screen.getByText("L")).toBeDefined()
  })

  it("calls onSelect when row is clicked", async () => {
    const onSelect = vi.fn()
    render(
      <PersonaItem persona={mockPersona} isActive={false}
        onSelect={onSelect} onNewChat={noop} onNewIncognitoChat={noop}
        onEdit={noop} onUnpin={noop} />
    )
    await userEvent.click(screen.getByText("Lyra"))
    expect(onSelect).toHaveBeenCalledWith(mockPersona)
  })

  it("opens context menu and calls onEdit when Edit is clicked", async () => {
    const onEdit = vi.fn()
    render(
      <PersonaItem persona={mockPersona} isActive={false}
        onSelect={noop} onNewChat={noop} onNewIncognitoChat={noop}
        onEdit={onEdit} onUnpin={noop} />
    )
    await userEvent.click(screen.getByLabelText("More options"))
    await userEvent.click(screen.getByText("Edit"))
    expect(onEdit).toHaveBeenCalledWith(mockPersona)
  })
})
