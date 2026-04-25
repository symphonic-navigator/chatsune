import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { KnowledgePills } from "../KnowledgePills"

describe("KnowledgePills", () => {
  it("renders search-source pill with book icon", () => {
    render(
      <KnowledgePills
        items={[
          {
            library_name: "Lore",
            document_title: "Andromeda",
            content: "…",
            score: 0.8,
            source: "search",
          },
        ]}
        overflow={null}
      />,
    )
    const pill = screen.getByText("Andromeda")
    expect(pill).toBeInTheDocument()
    expect(pill.closest("[data-source]")).toHaveAttribute("data-source", "search")
  })

  it("renders trigger-source pill with sparkles icon and triggered_by tooltip", () => {
    render(
      <KnowledgePills
        items={[
          {
            library_name: "Lore",
            document_title: "Andromeda",
            content: "…",
            source: "trigger",
            triggered_by: "andromedagalaxie",
          },
        ]}
        overflow={null}
      />,
    )
    const pill = screen.getByText("Andromeda")
    expect(pill.closest("[data-source]")).toHaveAttribute("data-source", "trigger")
    fireEvent.click(pill)
    expect(screen.getByText(/triggered by/i)).toHaveTextContent(
      "andromedagalaxie",
    )
  })

  it("renders overflow pill when caps were applied", () => {
    render(
      <KnowledgePills
        items={[]}
        overflow={{ dropped_count: 3, dropped_titles: ["A", "B", "C"] }}
      />,
    )
    const overflowPill = screen.getByText(/\+3 limited/i)
    expect(overflowPill).toBeInTheDocument()
    fireEvent.click(overflowPill)
    expect(screen.getByText("A")).toBeInTheDocument()
    expect(screen.getByText("B")).toBeInTheDocument()
    expect(screen.getByText("C")).toBeInTheDocument()
  })
})
