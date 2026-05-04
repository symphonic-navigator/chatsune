import { probeNow } from "../../core/health/healthMonitor"
import { FoxIcon } from "../../core/components/symbols"

export default function BackendUnavailablePage() {
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
        <FoxIcon />
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
            borderTopColor: "rgba(245,194,131,0.7)",
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
          checking...
        </span>
      </div>

      {/* Retry button */}
      <button
        onClick={() => void probeNow()}
        style={{
          marginBottom: "16px",
          padding: "6px 16px",
          fontSize: "12px",
          color: "rgba(255,255,255,0.5)",
          background: "rgba(255,255,255,0.06)",
          border: "1px solid rgba(255,255,255,0.1)",
          borderRadius: "6px",
          cursor: "pointer",
          fontFamily: "inherit",
        }}
      >
        Retry now
      </button>

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
