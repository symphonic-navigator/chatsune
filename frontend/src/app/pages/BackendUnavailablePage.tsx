import { useEffect, useRef, useState } from "react"
import { useEventStore } from "../../core/store/eventStore"

function baseUrl(): string {
  return import.meta.env.VITE_API_URL ?? ""
}

export default function BackendUnavailablePage() {
  const [retryCount, setRetryCount] = useState(0)
  const [checking, setChecking] = useState(false)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    async function checkHealth() {
      setChecking(true)
      try {
        const res = await fetch(`${baseUrl()}/api/health`, {
          method: "GET",
          cache: "no-store",
        })
        if (res.ok) {
          useEventStore.getState().setBackendAvailable(true)
          return
        }
      } catch {
        // Still unreachable
      }
      setChecking(false)
      setRetryCount((c) => c + 1)
    }

    // Check immediately on mount
    checkHealth()

    // Then every 5 seconds
    timerRef.current = setInterval(checkHealth, 5000)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [])

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        background: "#0f0d16",
        fontFamily: "'Inter', system-ui, sans-serif",
        zIndex: 9999,
      }}
    >
      {/* Fox */}
      <div
        style={{
          fontSize: "64px",
          lineHeight: 1,
          marginBottom: "24px",
          filter: "grayscale(0.3)",
          opacity: 0.9,
        }}
      >
        🦊
      </div>

      {/* App name */}
      <h1
        style={{
          fontSize: "20px",
          fontWeight: 600,
          color: "rgba(255,255,255,0.85)",
          letterSpacing: "0.02em",
          marginBottom: "8px",
        }}
      >
        Chatsune
      </h1>

      {/* Status message */}
      <p
        style={{
          fontSize: "14px",
          color: "rgba(255,255,255,0.45)",
          marginBottom: "32px",
          textAlign: "center",
          maxWidth: "320px",
          lineHeight: 1.5,
        }}
      >
        The backend is not responding.
        <br />
        Waiting for it to come back...
      </p>

      {/* Spinner */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "10px",
          marginBottom: "16px",
        }}
      >
        <div
          style={{
            width: "14px",
            height: "14px",
            borderRadius: "50%",
            border: "2px solid rgba(255,255,255,0.08)",
            borderTopColor: checking ? "rgba(245,194,131,0.7)" : "rgba(255,255,255,0.25)",
            animation: "spin 0.8s linear infinite",
          }}
        />
        <span
          style={{
            fontSize: "11px",
            color: "rgba(255,255,255,0.3)",
            fontFamily: "monospace",
            letterSpacing: "0.04em",
          }}
        >
          {checking ? "checking..." : `retry ${retryCount}`}
        </span>
      </div>

      {/* Hint */}
      <p
        style={{
          fontSize: "11px",
          color: "rgba(255,255,255,0.2)",
          textAlign: "center",
          maxWidth: "280px",
        }}
      >
        This page will reconnect automatically when the server is available.
      </p>

      <style>{`
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  )
}
