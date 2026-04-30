import { describe, it, expect } from 'vitest'
import { unified } from 'unified'
import rehypeParse from 'rehype-parse'
import rehypeStringify from 'rehype-stringify'
import rehypeIntegrationPills from '../rehypeIntegrationPills'

const ZWSP = '​'

function process(html: string, pillContents: Map<string, string>): string {
  return unified()
    .use(rehypeParse, { fragment: true })
    .use(rehypeIntegrationPills, { pillContents })
    .use(rehypeStringify)
    .processSync(html)
    .toString()
}

describe('rehypeIntegrationPills', () => {
  it('replaces a placeholder with a span carrying the pill content', () => {
    const id = '11111111-1111-4111-8111-111111111111'
    const placeholder = `${ZWSP}[effect:${id}]${ZWSP}`
    const out = process(
      `<p>before ${placeholder} after</p>`,
      new Map([[id, 'lovense vibrate 5s']]),
    )
    expect(out).toBe(
      '<p>before <span class="integration-pill">lovense vibrate 5s</span> after</p>',
    )
  })

  it('drops orphan placeholders when no pill content is registered', () => {
    const id = '22222222-2222-4222-8222-222222222222'
    const placeholder = `${ZWSP}[effect:${id}]${ZWSP}`
    const out = process(`<p>x ${placeholder} y</p>`, new Map())
    expect(out).toBe('<p>x  y</p>')
    expect(out).not.toContain('integration-pill')
    expect(out).not.toContain('[effect:')
  })

  it('handles multiple placeholders in a single text node', () => {
    const a = '11111111-1111-4111-8111-111111111111'
    const b = '22222222-2222-4222-8222-222222222222'
    const placeholder = (id: string) => `${ZWSP}[effect:${id}]${ZWSP}`
    const out = process(
      `<p>${placeholder(a)} and ${placeholder(b)}</p>`,
      new Map([
        [a, 'fx a'],
        [b, 'fx b'],
      ]),
    )
    expect(out).toBe(
      '<p><span class="integration-pill">fx a</span> and <span class="integration-pill">fx b</span></p>',
    )
  })

  it('does not transform placeholders inside <code>', () => {
    const id = '33333333-3333-4333-8333-333333333333'
    const placeholder = `${ZWSP}[effect:${id}]${ZWSP}`
    const out = process(
      `<p>see <code>${placeholder}</code> here</p>`,
      new Map([[id, 'unused']]),
    )
    expect(out).toContain('<code>')
    expect(out).not.toContain('integration-pill')
  })

  it('does not transform placeholders inside <pre>', () => {
    const id = '44444444-4444-4444-8444-444444444444'
    const placeholder = `${ZWSP}[effect:${id}]${ZWSP}`
    const out = process(
      `<pre><code>${placeholder}</code></pre>`,
      new Map([[id, 'unused']]),
    )
    expect(out).not.toContain('integration-pill')
  })

  it('leaves text without placeholders untouched', () => {
    const out = process(`<p>plain text</p>`, new Map([['x', 'y']]))
    expect(out).toBe('<p>plain text</p>')
  })
})
