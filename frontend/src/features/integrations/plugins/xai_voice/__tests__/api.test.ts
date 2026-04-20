import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock the auth-token provider BEFORE importing the module under test.
vi.mock('../../../../../core/api/client', () => ({
  currentAccessToken: () => 'TEST_TOKEN',
}))

import { transcribeXai, synthesiseXai, listXaiVoices } from '../api'

const fetchMock = vi.fn()

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})

describe('xai_voice api', () => {
  it('transcribeXai posts multipart with bearer token and returns text', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ text: 'hi' }), { status: 200 }),
    )
    const audio = new Blob([new Uint8Array([1, 2, 3])], { type: 'audio/webm;codecs=opus' })
    const text = await transcribeXai({ audio, mimeType: 'audio/webm;codecs=opus', language: 'en' })
    expect(text).toBe('hi')

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/integrations/xai_voice/voice/stt')
    expect(init.method).toBe('POST')
    expect(init.body).toBeInstanceOf(FormData)
    expect(init.headers.Authorization).toBe('Bearer TEST_TOKEN')
    // multipart filename tracks the MIME extension so servers using the
    // filename as a content-type hint disambiguate correctly.
    const form = init.body as FormData
    const file = form.get('audio') as File
    expect(file.name).toBe('audio.webm')
    expect(file.type).toBe('audio/webm;codecs=opus')
  })

  it('synthesiseXai posts JSON and returns a Blob', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(new Uint8Array([0xff, 0xfb]), {
        status: 200,
        headers: { 'content-type': 'audio/mpeg' },
      }),
    )
    const blob = await synthesiseXai({ text: 'hello', voiceId: 'v1' })
    expect(blob).toBeInstanceOf(Blob)
    expect(blob.type).toBe('audio/mpeg')

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/integrations/xai_voice/voice/tts')
    expect(init.method).toBe('POST')
    expect(init.headers['Content-Type']).toBe('application/json')
    expect(init.headers.Authorization).toBe('Bearer TEST_TOKEN')
    expect(JSON.parse(init.body as string)).toEqual({ text: 'hello', voice_id: 'v1' })
  })

  it('listXaiVoices returns the parsed voice list', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          voices: [{ id: 'v1', name: 'Voice One', language: null, gender: null }],
        }),
        { status: 200 },
      ),
    )
    const voices = await listXaiVoices()
    expect(voices).toHaveLength(1)
    expect(voices[0].id).toBe('v1')

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/integrations/xai_voice/voice/voices')
    expect(init.method).toBe('GET')
    expect(init.headers.Authorization).toBe('Bearer TEST_TOKEN')
  })

  it('throws on non-2xx and surfaces the backend message', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ error_code: 'voice_auth', message: 'bad key' }),
        { status: 401 },
      ),
    )
    await expect(listXaiVoices()).rejects.toThrow(/bad key/)
  })
})
