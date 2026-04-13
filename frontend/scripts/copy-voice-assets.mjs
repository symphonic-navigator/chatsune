/**
 * Copy ONNX Runtime WASM files and Silero VAD models to public/voice/
 * so Vite's dev server and production builds can serve them correctly.
 *
 * Run automatically via postinstall hook in package.json.
 */
import { copyFileSync, mkdirSync, readdirSync, statSync } from 'node:fs'
import { resolve, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const root = resolve(__dirname, '..')
const outDir = resolve(root, 'public', 'voice')
const pnpmDir = resolve(root, 'node_modules', '.pnpm')

mkdirSync(outDir, { recursive: true })

/** Recursively find a file by name under a directory (follows into all subdirs). */
function findFile(dir, name, depth = 0) {
  if (depth > 8) return null
  try {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry)
      const stat = statSync(full, { throwIfNoEntry: false })
      if (!stat) continue
      if (stat.isFile() && entry === name) return full
      if (stat.isDirectory()) {
        const found = findFile(full, name, depth + 1)
        if (found) return found
      }
    }
  } catch { /* skip permission errors */ }
  return null
}

const assets = [
  'ort-wasm-simd-threaded.wasm',
  'silero_vad_legacy.onnx',
  'silero_vad_v5.onnx',
]

for (const file of assets) {
  const src = findFile(pnpmDir, file)
  if (src) {
    copyFileSync(src, resolve(outDir, file))
    console.log(`  Copied ${file}`)
  } else {
    console.warn(`  Warning: ${file} not found in node_modules/.pnpm`)
  }
}

console.log('Voice assets copied to public/voice/')
