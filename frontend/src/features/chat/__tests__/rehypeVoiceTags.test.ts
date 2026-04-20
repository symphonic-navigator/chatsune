import { describe, it, expect } from 'vitest'
import { unified } from 'unified'
import rehypeParse from 'rehype-parse'
import rehypeStringify from 'rehype-stringify'
import rehypeVoiceTags from '../rehypeVoiceTags'

function process(html: string): string {
  return unified()
    .use(rehypeParse, { fragment: true })
    .use(rehypeVoiceTags)
    .use(rehypeStringify)
    .processSync(html)
    .toString()
}

describe('rehypeVoiceTags', () => {
  it('pills an inline tag in prose', () => {
    const out = process('<p>hi [laugh] there</p>')
    expect(out).toBe('<p>hi <span class="voice-tag">[laugh]</span> there</p>')
  })

  it('pills wrapping markers when the LLM text is rendered as escaped HTML', () => {
    // react-markdown yields text nodes for LLM output; when a user pastes raw
    // text containing <whisper>, markdown/rehype parses angle brackets as HTML
    // elements at parse time. To exercise the text-node path from the plugin,
    // HTML-encode the brackets in the test input.
    const out = process('<p>a &lt;whisper&gt;x&lt;/whisper&gt; b</p>')
    expect(out).toContain('<span class="voice-tag">&#x3C;whisper></span>')
    expect(out).toContain('<span class="voice-tag">&#x3C;/whisper></span>')
  })

  it('does not pill tags inside <code>', () => {
    const out = process('<p>see <code>[laugh]</code> here</p>')
    expect(out).toBe('<p>see <code>[laugh]</code> here</p>')
  })

  it('does not pill tags inside <pre>', () => {
    const out = process('<pre><code>&lt;whisper&gt;test&lt;/whisper&gt;</code></pre>')
    expect(out).not.toContain('voice-tag')
  })

  it('leaves unknown bracketed tokens alone', () => {
    const out = process('<p>see [1] and [note]</p>')
    expect(out).toBe('<p>see [1] and [note]</p>')
  })

  it('handles multiple tags in one text node', () => {
    const out = process('<p>a [laugh] b [pause] c</p>')
    expect(out).toBe('<p>a <span class="voice-tag">[laugh]</span> b <span class="voice-tag">[pause]</span> c</p>')
  })
})
