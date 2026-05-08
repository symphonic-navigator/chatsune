import { describe, expect, it } from 'vitest'

import { isAnthropicModel } from '../anthropicCache'

describe('isAnthropicModel', () => {
  it.each([
    'anthropic/claude-3-7-sonnet-20250219',
    '~anthropic/claude-opus-4-1',
    'claude-haiku-4-5',
    'claude-3-7-sonnet-20250219',
    'anthropic/claude-3.5-sonnet-vision',
    'ANTHROPIC/Claude-Sonnet-4-5',
  ])('matches %s', (slug) => {
    expect(isAnthropicModel(slug)).toBe(true)
  })

  it.each([
    'openai/gpt-4',
    'openai/gpt-4o',
    'meta/llama-3.3-70b',
    'mistral-large-latest',
    'anthropic/claude-instant-1',
    'meta/llama-claude-skin',
    '',
    'anthropic/',
    'claude',
    'claude-haiku/',
    'anthropic/claude-haiku/',
  ])('does not match %s', (slug) => {
    expect(isAnthropicModel(slug)).toBe(false)
  })
})
