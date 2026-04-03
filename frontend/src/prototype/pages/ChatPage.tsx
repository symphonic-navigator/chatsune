import { useState, useEffect, useRef } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { chatApi } from "../../core/api/chat"
import type { ChatSessionDto } from "../../core/api/chat"
import { eventBus } from "../../core/websocket/eventBus"
import { sendMessage } from "../../core/websocket/connection"
import type { BaseEvent } from "../../core/types/events"

interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  thinking?: string
}

type ContextStatus = "green" | "yellow" | "orange" | "red" | null

const contextStatusColour: Record<NonNullable<ContextStatus>, string> = {
  green: "bg-green-500",
  yellow: "bg-yellow-400",
  orange: "bg-orange-400",
  red: "bg-red-500",
}

export default function ChatPage() {
  const { personaId } = useParams<{ personaId: string }>()
  const navigate = useNavigate()

  const [session, setSession] = useState<ChatSessionDto | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [streamingContent, setStreamingContent] = useState<string>("")
  const [streamingThinking, setStreamingThinking] = useState<string>("")
  const [isStreaming, setIsStreaming] = useState(false)
  const [contextStatus, setContextStatus] = useState<ContextStatus>(null)
  const [error, setError] = useState<string | null>(null)
  const [inputText, setInputText] = useState("")
  const [initError, setInitError] = useState<string | null>(null)

  const bottomRef = useRef<HTMLDivElement>(null)
  const sessionRef = useRef<string | null>(null)
  const activeCorrelationRef = useRef<string | null>(null)
  // Refs mirror streaming state so stream.ended can read without side-effectful updaters
  const contentRef = useRef("")
  const thinkingRef = useRef("")

  // Auto-scroll to bottom on new content
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, streamingContent])

  // Create session on mount
  useEffect(() => {
    if (!personaId) return
    chatApi.createSession(personaId)
      .then((s) => {
        sessionRef.current = s.id
        setSession(s)
      })
      .catch((err) => setInitError(err instanceof Error ? err.message : "Failed to create session"))
  }, [personaId])

  // Subscribe to streaming events
  useEffect(() => {
    const unsubStart = eventBus.on("chat.stream.started", (event: BaseEvent) => {
      const payload = event.payload as { session_id?: string }
      if (payload.session_id !== sessionRef.current) return
      activeCorrelationRef.current = event.correlation_id
      contentRef.current = ""
      thinkingRef.current = ""
      setIsStreaming(true)
      setStreamingContent("")
      setStreamingThinking("")
      setError(null)
    })

    // Delta events are flat — correlation_id and delta are top-level
    const unsubContentDelta = eventBus.on("chat.content.delta", (event: BaseEvent) => {
      const flat = event as unknown as { type: string; correlation_id: string; delta: string }
      if (flat.correlation_id !== activeCorrelationRef.current) return
      contentRef.current += flat.delta
      setStreamingContent(contentRef.current)
    })

    const unsubThinkingDelta = eventBus.on("chat.thinking.delta", (event: BaseEvent) => {
      const flat = event as unknown as { type: string; correlation_id: string; delta: string }
      if (flat.correlation_id !== activeCorrelationRef.current) return
      thinkingRef.current += flat.delta
      setStreamingThinking(thinkingRef.current)
    })

    const unsubEnd = eventBus.on("chat.stream.ended", (event: BaseEvent) => {
      if (event.correlation_id !== activeCorrelationRef.current) return
      const payload = event.payload as { context_status?: string }

      // Read accumulated content from refs — no side effects in updaters
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant" as const,
          content: contentRef.current,
          thinking: thinkingRef.current || undefined,
        },
      ])

      contentRef.current = ""
      thinkingRef.current = ""
      setStreamingContent("")
      setStreamingThinking("")
      setIsStreaming(false)
      activeCorrelationRef.current = null

      if (payload.context_status) {
        setContextStatus(payload.context_status as ContextStatus)
      }
    })

    const unsubError = eventBus.on("chat.stream.error", (event: BaseEvent) => {
      const payload = event.payload as { user_message?: string; detail?: string }
      setError(payload.user_message ?? "An error occurred during streaming")
      setIsStreaming(false)
      setStreamingContent("")
      setStreamingThinking("")
      activeCorrelationRef.current = null
    })

    return () => {
      unsubStart()
      unsubContentDelta()
      unsubThinkingDelta()
      unsubEnd()
      unsubError()
    }
  }, [])

  const handleSend = () => {
    if (!session || !inputText.trim() || isStreaming) return

    const text = inputText.trim()
    setInputText("")

    // Optimistic user message
    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: "user", content: text },
    ])

    sendMessage({
      type: "chat.send",
      session_id: session.id,
      content: [{ type: "text", text }],
    })
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  if (initError) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4">
        <p className="text-sm text-red-600">{initError}</p>
        <button onClick={() => navigate("/personas")} className="rounded bg-gray-100 px-4 py-1.5 text-sm hover:bg-gray-200">
          Back to Personas
        </button>
      </div>
    )
  }

  if (!session) {
    return <p className="p-6 text-sm text-gray-400">Creating session...</p>
  }

  return (
    <div className="flex flex-col h-full max-h-[calc(100vh-4rem)]">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-gray-200 bg-white px-4 py-3 flex-shrink-0">
        <button
          onClick={() => navigate("/personas")}
          className="rounded bg-gray-100 px-3 py-1 text-sm hover:bg-gray-200"
        >
          Back
        </button>
        <span className="text-sm font-medium text-gray-700">
          Session: {session.id.slice(0, 8)}...
        </span>
        {contextStatus && (
          <span
            title={`Context: ${contextStatus}`}
            className={`ml-auto inline-block h-3 w-3 rounded-full ${contextStatusColour[contextStatus]}`}
          />
        )}
      </div>

      {/* Message list */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.map((msg) => (
          <div key={msg.id} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[70%] rounded-lg px-4 py-2 text-sm ${
                msg.role === "user"
                  ? "bg-blue-600 text-white"
                  : "bg-gray-100 text-gray-800"
              }`}
            >
              {msg.thinking && (
                <details className="mb-2 text-xs opacity-70">
                  <summary className="cursor-pointer select-none">Thinking</summary>
                  <pre className="mt-1 whitespace-pre-wrap font-sans">{msg.thinking}</pre>
                </details>
              )}
              <p className="whitespace-pre-wrap">{msg.content}</p>
            </div>
          </div>
        ))}

        {/* Streaming assistant bubble */}
        {isStreaming && (
          <div className="flex justify-start">
            <div className="max-w-[70%] rounded-lg bg-gray-100 px-4 py-2 text-sm text-gray-800">
              {streamingThinking && (
                <details open className="mb-2 text-xs opacity-70">
                  <summary className="cursor-pointer select-none">Thinking</summary>
                  <pre className="mt-1 whitespace-pre-wrap font-sans">{streamingThinking}</pre>
                </details>
              )}
              <p className="whitespace-pre-wrap">
                {streamingContent}
                <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-gray-500" />
              </p>
            </div>
          </div>
        )}

        {error && (
          <div className="flex justify-center">
            <p className="rounded bg-red-50 px-4 py-2 text-sm text-red-600">{error}</p>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="flex-shrink-0 border-t border-gray-200 bg-white px-4 py-3">
        <div className="flex gap-2 items-end">
          <textarea
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isStreaming}
            rows={2}
            placeholder="Type a message… (Enter to send, Shift+Enter for newline)"
            className="flex-1 resize-none rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none disabled:opacity-50"
          />
          <button
            onClick={handleSend}
            disabled={isStreaming || !inputText.trim()}
            className="rounded bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  )
}
