/**
 * Trigger a browser download of the given blob using a temporary anchor tag.
 *
 * No dependencies — just DOM APIs. Safe to call multiple times in a row; each
 * call creates and revokes its own object URL so there is no leak even if the
 * user quickly exports several archives back-to-back.
 */
export function triggerBlobDownload({
  blob,
  filename,
}: {
  blob: Blob
  filename: string
}): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = filename
  link.style.display = "none"
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  // Revoke on the next tick so the download has a chance to start. Revoking
  // synchronously is known to cancel the download on some browsers.
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

/**
 * Parse a filename out of a ``Content-Disposition`` header value.
 *
 * Supports the common ``attachment; filename="foo.tar.gz"`` shape as well
 * as the RFC 5987 ``filename*=UTF-8''foo.tar.gz`` form. Returns null when
 * no filename can be extracted, so callers can fall back to a default.
 */
export function parseContentDispositionFilename(
  headerValue: string | null,
): string | null {
  if (!headerValue) return null

  // Prefer the RFC 5987 ``filename*=`` form when present — it is the
  // canonical way to ship non-ASCII filenames.
  const rfc5987 = /filename\*\s*=\s*(?:[^']*'[^']*')?([^;]+)/i.exec(headerValue)
  if (rfc5987 && rfc5987[1]) {
    try {
      return decodeURIComponent(rfc5987[1].trim().replace(/^"|"$/g, ""))
    } catch {
      // Fall through to the plain filename= form below.
    }
  }

  const plain = /filename\s*=\s*("([^"]+)"|([^;]+))/i.exec(headerValue)
  if (plain) {
    const quoted = plain[2]
    const bare = plain[3]
    const raw = (quoted ?? bare ?? "").trim()
    if (raw) return raw
  }

  return null
}
