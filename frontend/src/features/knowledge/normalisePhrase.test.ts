import { describe, expect, it } from "vitest"
import { normalisePhrase } from "./normalisePhrase"

describe("normalisePhrase", () => {
  it("lowercases", () => {
    expect(normalisePhrase("Andromeda")).toBe("andromeda")
  })

  it("collapses whitespace", () => {
    expect(normalisePhrase("dragon  ball   z")).toBe("dragon ball z")
  })

  it("trims", () => {
    expect(normalisePhrase("  hello  ")).toBe("hello")
  })

  it("casefolds German ß", () => {
    expect(normalisePhrase("Straße")).toBe("strasse")
  })

  it("composes Unicode (NFC)", () => {
    const decomposed = "café"
    const composed = "café"
    expect(normalisePhrase(decomposed)).toBe(normalisePhrase(composed))
    expect(normalisePhrase(decomposed)).toBe("café")
  })

  it("keeps punctuation", () => {
    expect(normalisePhrase("Andromeda-Galaxie!")).toBe("andromeda-galaxie!")
  })

  it("keeps emoji", () => {
    expect(normalisePhrase("🐉 dragon")).toBe("🐉 dragon")
  })

  it("keeps CJK", () => {
    expect(normalisePhrase("アンドロメダ銀河")).toBe("アンドロメダ銀河")
  })

  it("is idempotent", () => {
    const s = "  Foo BAR  baz!  "
    expect(normalisePhrase(normalisePhrase(s))).toBe(normalisePhrase(s))
  })

  it("collapses various whitespace classes", () => {
    expect(normalisePhrase("a	b c　d")).toBe("a b c d")
  })

  it("returns empty string for blank input", () => {
    expect(normalisePhrase("")).toBe("")
    expect(normalisePhrase("   ")).toBe("")
  })
})
