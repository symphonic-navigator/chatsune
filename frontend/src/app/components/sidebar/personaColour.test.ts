import { describe, it, expect } from "vitest"
import { personaGradient, personaInitial } from "./personaColour"
import type { PersonaDto } from "../../../core/types/persona"

const base: PersonaDto = {
  id: "abc123",
  user_id: "u1",
  name: "Lyra",
  tagline: "",
  model_unique_id: "test:model",
  system_prompt: "",
  temperature: 0.8,
  reasoning_enabled: false,
  soft_cot_enabled: false,
  vision_fallback_model: null,
  nsfw: false,
  use_memory: true,
  colour_scheme: "heart",
  display_order: 0,
  monogram: "L",
  pinned: false,
  profile_image: null,
  profile_crop: null,
  mcp_config: null,
  integrations_config: null,
  voice_config: null,
  created_at: "2026-01-01",
  updated_at: "2026-01-01",
}

describe("personaInitial", () => {
  it("returns uppercased first character of name", () => {
    expect(personaInitial({ ...base, name: "lyra" })).toBe("L")
    expect(personaInitial({ ...base, name: "Atlas" })).toBe("A")
  })
})

describe("personaGradient", () => {
  it("uses colour_scheme if it is a hex colour", () => {
    const g = personaGradient({ ...base, colour_scheme: "#7c5cbf" as unknown as PersonaDto["colour_scheme"] })
    expect(g).toContain("#7c5cbf")
  })

  it("returns a gradient string for personas without colour_scheme", () => {
    const g = personaGradient({ ...base, colour_scheme: "" as unknown as PersonaDto["colour_scheme"] })
    expect(g).toMatch(/linear-gradient/)
  })

  it("returns a consistent gradient for the same persona id", () => {
    const g1 = personaGradient({ ...base, colour_scheme: "" as unknown as PersonaDto["colour_scheme"] })
    const g2 = personaGradient({ ...base, colour_scheme: "" as unknown as PersonaDto["colour_scheme"] })
    expect(g1).toBe(g2)
  })
})
