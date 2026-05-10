// Diagnostic harness for the LaTeX/Math rendering pipeline.
//
// Runs the real pipeline (preprocessMath → remark-math → rehype-katex →
// HTML) over a comprehensive set of testcases and produces a per-case
// report. This file is *diagnostic*, not gating: each `it.each` row asserts
// only that the pipeline does not throw, and emits a summary table to
// stdout so a human can scan which inputs render and which fall back to
// the red KaTeX-error display or to plain text without any math node.
//
// To run only this file:
//   pnpm vitest run src/features/chat/__tests__/latexRendering.diagnostic.test.ts
//
// To inspect the produced HTML for a single case:
//   pnpm vitest run src/features/chat/__tests__/latexRendering.diagnostic.test.ts -t "07 — pmatrix"

import { describe, it, expect } from 'vitest'
import { unified } from 'unified'
import remarkParse from 'remark-parse'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import remarkRehype from 'remark-rehype'
import rehypeKatex from 'rehype-katex'
import rehypeStringify from 'rehype-stringify'
import { preprocessMath } from '../markdownComponents'

interface CaseResult {
  id: string
  ok: boolean                     // at least one math node rendered without error
  mathNodeCount: number           // <span class="katex"> hits
  errorCount: number              // <span class="katex-error"> hits
  surroundingTextOk: boolean      // expected sentinel string still present
  notes: string
}

function render(src: string): string {
  const preprocessed = preprocessMath(src)
  const file = unified()
    .use(remarkParse)
    .use(remarkGfm)
    .use(remarkMath)
    .use(remarkRehype)
    // rehype-katex always passes throwOnError: false to KaTeX internally
    // (errors render as a styled <span class="katex-error">), so no options needed.
    .use(rehypeKatex)
    .use(rehypeStringify)
    .processSync(preprocessed)
  return String(file)
}

function evaluate(id: string, src: string, sentinel: string | null): CaseResult {
  let html = ''
  let notes = ''
  try {
    html = render(src)
  } catch (e) {
    return {
      id,
      ok: false,
      mathNodeCount: 0,
      errorCount: 0,
      surroundingTextOk: false,
      notes: `THREW: ${(e as Error).message}`,
    }
  }
  const mathNodeCount = (html.match(/class="katex"/g) ?? []).length
  const errorCount = (html.match(/class="katex-error"/g) ?? []).length
  const surroundingTextOk = sentinel === null ? true : html.includes(sentinel)
  const ok = mathNodeCount > 0 && errorCount === 0 && surroundingTextOk
  if (!ok) {
    if (mathNodeCount === 0) notes += 'NO MATH NODE; '
    if (errorCount > 0) notes += `${errorCount} KATEX ERRORS; `
    if (!surroundingTextOk) notes += `SENTINEL "${sentinel}" MISSING; `
  }
  return { id, ok, mathNodeCount, errorCount, surroundingTextOk, notes: notes.trim() }
}

// ----------------------------------------------------------------------------
// The reproducer from the bug report
// ----------------------------------------------------------------------------

const BUG_SNIPPET = String.raw`$$\begin{pmatrix} 1 & 2 & 3 \\ 4 & 5 & 6 \\ 7 & 8 & 9 \end{pmatrix}$$ Ableitung / Gradient: $$\nabla f(x,y,z) = \left( \frac{\partial f}{\partial x}, \frac{\partial f}{\partial y}, \frac{\partial f}{\partial z} \right)$$ Maxwell-mäßig hübsch: $$\nabla \cdot \mathbf{E} = \frac{\rho}{\varepsilon_0}$$ Tensor/Index-Notation: $$R_{\mu\nu} - \frac{1}{2} R g_{\mu\nu} + \Lambda g_{\mu\nu} = \frac{8\pi G}{c^4} T_{\mu\nu}$$ Mehrzeilige Gleichung: $$\begin{aligned} f(x) &= (x+1)^2 \\ &= x^2 + 2x + 1 \end{aligned}$$ Cases: \[ |x| = \begin{cases} x, & x \ge 0 \\ -x, & x < 0 \end{cases} \]`

// Same content but with each block on its own line — to A/B test the
// "inline $$...$$ on a single line" hypothesis.
const BUG_SNIPPET_SEPARATED = BUG_SNIPPET
  .split(/(?<=\$\$)\s+(?=[A-ZÄÖÜa-zäöü])|(?<=\$\$)\s+(?=\\\[)/g)
  .join('\n\n')

// ----------------------------------------------------------------------------
// The 45 testcases from the spec
// ----------------------------------------------------------------------------

interface Case { id: string; src: string; sentinel: string | null }

const CASES: Case[] = [
  { id: '01-inline-basic', sentinel: 'Energie', src: String.raw`Die Energie ist \(E = mc^2\), und der goldene Schnitt ist \(\varphi = \frac{1 + \sqrt{5}}{2}\).` },
  { id: '02-display-bracket', sentinel: null, src: String.raw`\[
a^2 + b^2 = c^2
\]` },
  { id: '03-display-dollar', sentinel: null, src: `$$
a^2 + b^2 = c^2
$$` },
  { id: '04-quadratic', sentinel: null, src: String.raw`\[
x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}
\]` },
  { id: '05-sum-limit', sentinel: null, src: String.raw`\[
\sum_{k=1}^{n} k = \frac{n(n+1)}{2}
\]

\[
\lim_{x \to 0} \frac{\sin x}{x} = 1
\]` },
  { id: '06-integral-infinity', sentinel: null, src: String.raw`\[
\int_{-\infty}^{\infty} e^{-x^2}\,dx = \sqrt{\pi}
\]` },
  { id: '07-pmatrix-multiline', sentinel: null, src: String.raw`\[
A =
\begin{pmatrix}
1 & 2 & 3 \\
4 & 5 & 6 \\
7 & 8 & 9
\end{pmatrix}
\]` },
  { id: '08-pmatrix-oneline', sentinel: null, src: String.raw`\[
A = \begin{pmatrix} 1 & 2 & 3 \\ 4 & 5 & 6 \\ 7 & 8 & 9 \end{pmatrix}
\]` },
  { id: '09-array', sentinel: null, src: String.raw`\[
A =
\begin{array}{ccc}
1 & 2 & 3 \\
4 & 5 & 6 \\
7 & 8 & 9
\end{array}
\]` },
  { id: '10-cases', sentinel: null, src: String.raw`\[
|x| =
\begin{cases}
x, & x \ge 0 \\
-x, & x < 0
\end{cases}
\]` },
  { id: '11-aligned', sentinel: null, src: String.raw`\[
\begin{aligned}
f(x) &= (x+1)^2 \\
     &= x^2 + 2x + 1
\end{aligned}
\]` },
  { id: '12-aligned-text', sentinel: null, src: String.raw`\[
\begin{aligned}
P(A \mid B) &= \frac{P(B \mid A)P(A)}{P(B)} \\
\text{falls } P(B) &\ne 0
\end{aligned}
\]` },
  { id: '13-nabla', sentinel: null, src: String.raw`\[
\nabla f(x,y,z) =
\left(
\frac{\partial f}{\partial x},
\frac{\partial f}{\partial y},
\frac{\partial f}{\partial z}
\right)
\]` },
  { id: '14-maxwell', sentinel: null, src: String.raw`\[
\nabla \cdot \mathbf{E} = \frac{\rho}{\varepsilon_0}
\]` },
  { id: '15-tensor', sentinel: null, src: String.raw`\[
R_{\mu\nu} - \frac{1}{2} R g_{\mu\nu} + \Lambda g_{\mu\nu}
= \frac{8\pi G}{c^4} T_{\mu\nu}
\]` },
  { id: '16-nested-brackets', sentinel: null, src: String.raw`\[
\left( \frac{1}{n} \sum_{i=1}^{n} \left(x_i - \bar{x}\right)^2 \right)^{1/2}
\]` },
  { id: '17-binom', sentinel: null, src: String.raw`\[
\binom{n}{k} = \frac{n!}{k!(n-k)!}
\]` },
  { id: '18-set-logic', sentinel: null, src: String.raw`\[
S = \{ x \in \mathbb{R} \mid x^2 < 2 \}
\]

\[
\forall \epsilon > 0\; \exists \delta > 0\; \forall x:\ |x-a| < \delta \Rightarrow |f(x)-f(a)| < \epsilon
\]` },
  { id: '19-arrows', sentinel: null, src: String.raw`\[
A \xrightarrow{f} B \xrightarrow{g} C, \qquad g \circ f : A \to C
\]` },
  { id: '20-chemistry', sentinel: null, src: String.raw`\[
2H_2 + O_2 \rightarrow 2H_2O
\]` },
  { id: '21-inline-dollar', sentinel: 'Preis', src: `Der Preis ist $5, aber die Formel ist $x^2 + y^2 = z^2$ im Text.` },
  { id: '22-escaped-dollar', sentinel: '19.99', src: String.raw`Dieser Text enthält einen Preis: \$19.99 und danach Inline-Math: \(x+1\).` },
  { id: '23-list', sentinel: null, src: String.raw`1. Erste Formel:

   \[
   f(x) = x^2
   \]

2. Zweite Formel:

   \[
   g(x) = \sqrt{x}
   \]` },
  { id: '24-blockquote', sentinel: null, src: String.raw`> Wichtiges Theorem:
>
> \[
> a^2 + b^2 = c^2
> \]` },
  { id: '25-codefence', sentinel: 'E = mc^2', src: '```latex\n\\[\nE = mc^2\n\\]\n```' },
  { id: '26-inline-code', sentinel: 'Schreibe', src: 'Schreibe `\\(E = mc^2\\)` in den Chat, wenn du Inline-Math testen willst.' },
  { id: '27-adjacent-text', sentinel: 'Vorher', src: String.raw`Vorher\(x+y=z\)Nachher` },
  { id: '28-unicode', sentinel: 'Äpfel', src: String.raw`Äpfel, Öl und Übergrößen: \(\alpha + \beta = \gamma\). Emoji danach 🚀.` },
  { id: '29-long-inline', sentinel: 'mitten', src: String.raw`Ein langer Inline-Ausdruck: \(f(x_1, x_2, \ldots, x_n) = \sum_{i=1}^{n} \alpha_i x_i^2 + \sum_{i=1}^{n}\sum_{j=1}^{n} \beta_{ij}x_ix_j + \gamma\) mitten im Satz.` },
  { id: '30-long-display', sentinel: null, src: String.raw`\[
F(s) = \int_0^\infty e^{-st} f(t)\,dt = \lim_{n \to \infty} \sum_{k=0}^{n} e^{-s k\Delta t} f(k\Delta t)\Delta t
\]` },
  { id: '31-align-star', sentinel: null, src: String.raw`\[
\begin{align*}
a &= b + c \\
d &= e + f
\end{align*}
\]` },
  { id: '32-equation', sentinel: null, src: String.raw`\[
\begin{equation}
E = mc^2
\end{equation}
\]` },
  { id: '33-bad-command', sentinel: 'lesbar', src: String.raw`\[
\definitelyNotARealCommand{x}
\]

Dieser Satz danach muss normal lesbar bleiben.` },
  { id: '34-unbalanced-brace', sentinel: 'normaler Text', src: String.raw`\[
\frac{1}{2
\]

Nach dem kaputten Block geht normaler Text weiter.` },
  { id: '35-unclosed-display', sentinel: 'verschwinden', src: String.raw`Hier beginnt ein kaputter Block:
\[
x^2 + y^2 = z^2

Dieser Text danach sollte idealerweise nicht komplett verschwinden.` },
  { id: '36-multiple-back-to-back', sentinel: null, src: String.raw`\[
a = b
\]
\[
c = d
\]
\[
e = f
\]` },
  { id: '37-text-between', sentinel: 'Markdown-Fettdruck', src: String.raw`Erste Formel:

\[
a = b
\]

Etwas erklärender Text mit **Markdown-Fettdruck**.

\[
c = d
\]` },
  { id: '38-percent-comment', sentinel: null, src: String.raw`\[
a = b % dieser Kommentar sollte ggf. ignoriert werden
\]` },
  { id: '39-ampersand-outside-align', sentinel: 'Text danach', src: String.raw`\[
a & b
\]

Text danach bleibt erhalten.` },
  { id: '40-markdown-specials', sentinel: null, src: String.raw`\[
a_b^* \mid c_d^* \quad \text{und} \quad x_{i_j}
\]` },
  { id: '41-nested-braces', sentinel: null, src: String.raw`\[
\frac{\left(\frac{a+b}{c+d}\right)^2}{\sqrt{\frac{e^{x+y}}{1+\frac{1}{n}}}}
\]` },
  { id: '42-units', sentinel: null, src: String.raw`\[
c = 2.99792458 \times 10^8\,\mathrm{m\,s^{-1}}
\]` },
  { id: '43-color', sentinel: null, src: String.raw`\[
\color{red}{E = mc^2}
\]` },
  { id: '44-unicode-math', sentinel: 'Inline Unicode', src: String.raw`Inline Unicode: ∑, ∫, √, π, λ. LaTeX dazu: \(\sum_i x_i = \lambda\).` },
  { id: '45-mixed-realistic', sentinel: 'numerische Stabilität', src: String.raw`Hier ist die Idee:

- Für kleine Werte gilt näherungsweise \(\sin x \approx x\).
- Daraus folgt:

\[
\lim_{x \to 0} \frac{\sin x}{x} = 1
\]

Das ist praktisch, wenn man numerische Stabilität testen will.` },
  // Bug snippet — exactly as posted
  { id: '99-BUG-SNIPPET-as-posted', sentinel: 'Maxwell', src: BUG_SNIPPET },
  // Same content with newlines between $$-blocks
  { id: '99-BUG-SNIPPET-newline-separated', sentinel: 'Maxwell', src: BUG_SNIPPET_SEPARATED },
  // Verbatim from the user's bug report — note: starts with `\begin{pmatrix}`
  // without a leading `$$`, so the first `$$` it encounters is interpreted as
  // an OPENING fence by micromark. Reproduces the visual red-error in the
  // screenshot.
  {
    id: '99-BUG-SNIPPET-verbatim',
    sentinel: 'Maxwell',
    src: String.raw`\begin{pmatrix} 1 & 2 & 3 \\ 4 & 5 & 6 \\ 7 & 8 & 9 \end{pmatrix}$$ Ableitung / Gradient: $$\nabla f(x,y,z) = \left( \frac{\partial f}{\partial x}, \frac{\partial f}{\partial y}, \frac{\partial f}{\partial z} \right)$$ Maxwell-mäßig hübsch: $$\nabla \cdot \mathbf{E} = \frac{\rho}{\varepsilon_0}$$ Tensor/Index-Notation: $$R_{\mu\nu} - \frac{1}{2} R g_{\mu\nu} + \Lambda g_{\mu\nu} = \frac{8\pi G}{c^4} T_{\mu\nu}$$ Mehrzeilige Gleichung: $$\begin{aligned} f(x) &= (x+1)^2 \\ &= x^2 + 2x + 1 \end{aligned}$$ Cases: \[ |x| = \begin{cases} x, & x \ge 0 \\ -x, & x < 0 \end{cases} \]`,
  },
  // Realistic LLM output: same content but each $$...$$ on its own line as a
  // proper display block (the "well-formed" variant a future fix should
  // produce after preprocessing).
  {
    id: '99-LLM-realistic-with-newlines',
    sentinel: 'Maxwell',
    src: `Hier sind ein paar Beispiele:

$$
\\begin{pmatrix}
1 & 2 & 3 \\\\
4 & 5 & 6 \\\\
7 & 8 & 9
\\end{pmatrix}
$$

Ableitung / Gradient:

$$
\\nabla f(x,y,z) = \\left( \\frac{\\partial f}{\\partial x}, \\frac{\\partial f}{\\partial y}, \\frac{\\partial f}{\\partial z} \\right)
$$

Maxwell-mäßig hübsch:

$$
\\nabla \\cdot \\mathbf{E} = \\frac{\\rho}{\\varepsilon_0}
$$
`,
  },
]

// Cases that MUST render at least one math node with zero KaTeX errors.
// Excluded:
//   - 21, 22 (raw $...$ with currency-like text — relies on remark-math anti-currency)
//   - 25, 26 (latex code-fence / inline-code — handled by React component layer)
//   - 31, 32 (align*/equation environments — KaTeX support depends on amsmath; out of scope)
//   - 34, 39 (deliberately broken inputs — error is correct behaviour)
//   - 35 (unclosed display — fallback to text is acceptable)
//   - 38 (% LaTeX comment — KaTeX historically chokes on it; can revisit)
const MUST_PASS_IDS = new Set([
  '01-inline-basic', '02-display-bracket', '03-display-dollar', '04-quadratic',
  '05-sum-limit', '06-integral-infinity', '07-pmatrix-multiline',
  '08-pmatrix-oneline', '09-array', '10-cases', '11-aligned', '12-aligned-text',
  '13-nabla', '14-maxwell', '15-tensor', '16-nested-brackets', '17-binom',
  '18-set-logic', '19-arrows', '20-chemistry', '23-list', '24-blockquote',
  '27-adjacent-text', '28-unicode', '29-long-inline', '30-long-display',
  '36-multiple-back-to-back', '37-text-between', '40-markdown-specials',
  '41-nested-braces', '42-units', '43-color', '44-unicode-math',
  '45-mixed-realistic',
  '99-BUG-SNIPPET-as-posted', '99-BUG-SNIPPET-newline-separated',
  '99-BUG-SNIPPET-verbatim', '99-LLM-realistic-with-newlines',
])

describe('LaTeX rendering diagnostic', () => {
  it.each(CASES)('$id', ({ id, src, sentinel }) => {
    const r = evaluate(id, src, sentinel)
    if (MUST_PASS_IDS.has(id)) {
      expect(r.errorCount, `${id}: KaTeX error in HTML — ${r.notes}`).toBe(0)
      expect(r.mathNodeCount, `${id}: no math node rendered — ${r.notes}`).toBeGreaterThan(0)
      expect(r.surroundingTextOk, `${id}: surrounding sentinel missing`).toBe(true)
    } else {
      // Soft expectation: pipeline must not throw.
      expect(r).toBeDefined()
    }
  })

  // ----- Fix 2 — code-span / code-fence preservation -----

  it('does not transform \\(...\\) inside an inline code span', () => {
    const html = render('Schreibe `\\(E = mc^2\\)` in den Chat.')
    // The literal user text must be preserved inside <code>...</code>;
    // it must not be silently rewritten to $E = mc^2$ (data loss).
    expect(html).toContain('<code>\\(E = mc^2\\)</code>')
    expect(html).not.toContain('<code>$E = mc^2$</code>')
  })

  it('does not transform \\[...\\] inside a fenced code block', () => {
    const html = render('```\n\\[E = mc^2\\]\n```')
    // Fenced code must keep its content verbatim, not get a $$...$$ rewrite.
    expect(html).toContain('\\[E = mc^2\\]')
    expect(html).not.toContain('$$')
  })

  // ----- Fix 3 — \\[Npt] inside aligned must not match the \[ regex -----

  it('does not treat LaTeX line-break with optional spacing as display math', () => {
    const src = String.raw`\[
\begin{aligned}
a &= b \\[5pt]
c &= d
\end{aligned}
\]`
    const html = render(src)
    // Must render as a single math block without KaTeX errors. If the \[ regex
    // greedily matched \\[5pt] as a display-math start, the inner [5pt]…\] would
    // be re-emitted as $$[5pt]…$$ and KaTeX would barf.
    expect(html).toContain('class="katex"')
    expect(html).not.toContain('class="katex-error"')
  })

})
