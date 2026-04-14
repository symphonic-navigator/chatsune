import { describe, it, expect, beforeEach, vi } from 'vitest'
import { probeCapabilities, computeFingerprint, CACHE_VERSION } from '../capabilityProbe'

function installGpu(
  features: string[] | null,
  info: { vendor: string; architecture: string } | null,
) {
  const adapter = features === null ? null : {
    features: new Set(features),
    info,
  }
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: {
      gpu: {
        requestAdapter: vi.fn().mockResolvedValue(adapter),
      },
    },
  })
}

function removeGpu() {
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: {},
  })
}

describe('probeCapabilities', () => {
  beforeEach(() => {
    // ensure each test starts clean — implementation memoises by default
  })

  it('reports webgpu=false when navigator.gpu is missing', async () => {
    removeGpu()
    const caps = await probeCapabilities({ forceFresh: true })
    expect(caps.webgpu).toBe(false)
    expect(caps.shaderF16).toBe(false)
    expect(caps.adapterInfo).toBeNull()
  })

  it('reports webgpu=false when requestAdapter resolves null', async () => {
    installGpu(null, null)
    const caps = await probeCapabilities({ forceFresh: true })
    expect(caps.webgpu).toBe(false)
  })

  it('reports shaderF16=true when the adapter advertises it', async () => {
    installGpu(['shader-f16'], { vendor: 'amd', architecture: 'rdna3' })
    const caps = await probeCapabilities({ forceFresh: true })
    expect(caps.webgpu).toBe(true)
    expect(caps.shaderF16).toBe(true)
    expect(caps.adapterInfo).toEqual({ vendor: 'amd', architecture: 'rdna3' })
  })

  it('reports shaderF16=false when the feature set omits it', async () => {
    installGpu([], { vendor: 'nvidia', architecture: 'ampere' })
    const caps = await probeCapabilities({ forceFresh: true })
    expect(caps.webgpu).toBe(true)
    expect(caps.shaderF16).toBe(false)
  })

  it('memoises within a session — second call does not reprobe', async () => {
    installGpu(['shader-f16'], { vendor: 'amd', architecture: 'rdna3' })
    const first = await probeCapabilities({ forceFresh: true })
    installGpu([], { vendor: 'other', architecture: 'other' })
    const second = await probeCapabilities()
    expect(second).toBe(first) // same reference
  })
})

describe('computeFingerprint', () => {
  it('uses wasm token when webgpu is false', () => {
    const fp = computeFingerprint({ webgpu: false, shaderF16: false, adapterInfo: null })
    expect(fp).toBe(`wasm/v${CACHE_VERSION}`)
  })

  it('encodes vendor, architecture, and shader-f16 flag for webgpu', () => {
    const fp = computeFingerprint({
      webgpu: true,
      shaderF16: true,
      adapterInfo: { vendor: 'amd', architecture: 'rdna3' },
    })
    expect(fp).toBe(`webgpu/amd/rdna3/f16:true/v${CACHE_VERSION}`)
  })

  it('falls back to "unknown" tokens when adapterInfo is null', () => {
    const fp = computeFingerprint({
      webgpu: true,
      shaderF16: false,
      adapterInfo: null,
    })
    expect(fp).toBe(`webgpu/unknown/unknown/f16:false/v${CACHE_VERSION}`)
  })
})
