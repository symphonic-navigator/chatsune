// Thin wrapper around @mistralai/mistralai. Browser-side, BYOK. All calls
// take the API key per invocation — the secret lives only in the secrets store.

import { Mistral } from '@mistralai/mistralai'
import type {
  AudioTranscriptionRequest,
  TranscriptionResponse,
  SpeechRequest,
} from '@mistralai/mistralai/models/components'
import type { SpeechResponse } from '@mistralai/mistralai/models/operations'

function client(apiKey: string): Mistral {
  return new Mistral({ apiKey })
}

export interface TranscribeParams {
  apiKey: string
  audio: Blob
  language?: string
}

export async function transcribe({ apiKey, audio, language }: TranscribeParams): Promise<string> {
  const file = new File([audio], 'recording.wav', { type: audio.type || 'audio/wav' })

  const request: AudioTranscriptionRequest = {
    model: 'voxtral-mini-latest',
    file,
    ...(language != null ? { language } : {}),
  }

  const result: TranscriptionResponse = await client(apiKey).audio.transcriptions.complete(request)
  return result.text
}

export interface SynthesiseParams {
  apiKey: string
  text: string
  voiceId: string
}

export async function synthesise({ apiKey, text, voiceId }: SynthesiseParams): Promise<Blob> {
  const request: SpeechRequest = {
    model: 'voxtral-tts-latest',
    input: text,
    voiceId,
    stream: false,
  }

  // SpeechResponse carries base64-encoded audio data
  const result = await client(apiKey).audio.speech.complete(request) as SpeechResponse
  const binary = atob(result.audioData)
  const bytes = Uint8Array.from(binary, (ch) => ch.charCodeAt(0))
  return new Blob([bytes], { type: 'audio/mpeg' })
}
