import { render, screen } from "@testing-library/react"
import { describe, it, expect, vi } from "vitest"
import { ModelBrowser } from "../ModelBrowser"
import type { EnrichedModelDto } from "../../../../core/types/llm"

function model(over: Partial<EnrichedModelDto>): EnrichedModelDto {
  return {
    unique_id: "p:m",
    model_id: "m",
    display_name: "M",
    provider_id: "p",
    provider_display_name: "P",
    context_window: 8000,
    parameter_count: null,
    raw_parameter_count: null,
    quantisation_level: null,
    supports_tool_calls: false,
    supports_vision: false,
    supports_reasoning: false,
    user_config: null,
    curation: null,
    ...over,
  } as EnrichedModelDto
}

describe("ModelBrowser lockedFilters", () => {
  it("forces vision filter on, disables its toggle, and hides non-vision models", () => {
    const visionModel = model({ unique_id: "p:vis", display_name: "VisOne", supports_vision: true })
    const plainModel = model({ unique_id: "p:plain", display_name: "PlainOne", supports_vision: false })

    render(
      <ModelBrowser
        models={[visionModel, plainModel]}
        onSelect={vi.fn()}
        lockedFilters={{ capVision: true }}
      />,
    )

    expect(screen.getByText("VisOne")).toBeInTheDocument()
    expect(screen.queryByText("PlainOne")).not.toBeInTheDocument()

    const visionBtn = screen.getByTitle("Vision (required)")
    expect(visionBtn).toBeDisabled()
  })
})
