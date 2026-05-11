import { useState } from 'react'

import type { ConversationItemDto } from '../../core/api/chatGptImportApi'
import { useChatGptImportStore } from '../../core/store/chatGptImportStore'

import { ConversationPreviewExpanded } from './ConversationPreviewExpanded'

interface Props {
  conv: ConversationItemDto
  currentPersonaId: string
  personaNames: Record<string, string>
}

export function ConversationRow({ conv, currentPersonaId, personaNames }: Props) {
  const [expanded, setExpanded] = useState(false)
  const isSelected = useChatGptImportStore((s) =>
    s.selectedConversationIds.has(conv.chatgpt_conversation_id),
  )
  const isImporting = useChatGptImportStore((s) =>
    s.importingConversationIds.has(conv.chatgpt_conversation_id),
  )
  const toggle = useChatGptImportStore((s) => s.toggleSelected)

  const inThisPersona = conv.imports.find((i) => i.persona_id === currentPersonaId)
  const inOtherPersonas = conv.imports.filter((i) => i.persona_id !== currentPersonaId)

  return (
    <div className="p-3 border-b border-white/5 hover:bg-white/5 transition">
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          checked={isSelected}
          onChange={() => toggle(conv.chatgpt_conversation_id)}
          disabled={isImporting}
          aria-label={`Select ${conv.title}`}
          className="mt-1 cursor-pointer"
        />
        <div
          className="flex-1 min-w-0 cursor-pointer"
          onClick={() => setExpanded((v) => !v)}
          role="button"
          aria-expanded={expanded}
        >
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-white font-medium truncate">
              {conv.title || '(untitled)'}
            </h3>
            {conv.default_model_slug && (
              <span className="font-mono text-xs px-1.5 py-0.5 bg-white/10 rounded text-white/70">
                {conv.default_model_slug}
              </span>
            )}
            {isImporting && (
              <span className="text-xs text-amber-300">importing…</span>
            )}
          </div>
          <p className="text-xs text-white/50 mt-0.5">
            {new Date(conv.create_time).toLocaleDateString()} ·{' '}
            {conv.message_count} messages
          </p>
          <div className="flex flex-wrap gap-1 mt-1">
            {inThisPersona && (
              <span className="text-xs px-2 py-0.5 bg-emerald-900/40 text-emerald-200 rounded">
                in this persona, imported{' '}
                {new Date(inThisPersona.imported_at).toLocaleDateString()}
              </span>
            )}
            {inOtherPersonas.map((i) => {
              const name = i.persona_name || personaNames[i.persona_id] || 'another persona'
              return (
                <span
                  key={i.session_id}
                  className="text-xs px-2 py-0.5 bg-white/10 text-white/60 rounded"
                >
                  in &ldquo;{name}&rdquo;, imported{' '}
                  {new Date(i.imported_at).toLocaleDateString()}
                </span>
              )
            })}
          </div>
        </div>
      </div>
      {expanded && <ConversationPreviewExpanded conv={conv} />}
    </div>
  )
}
