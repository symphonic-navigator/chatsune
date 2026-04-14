export interface VoiceCapabilities {
  webgpu: boolean
  shaderF16: boolean
  adapterInfo: { vendor: string; architecture: string } | null
}
