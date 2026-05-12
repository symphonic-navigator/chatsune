import { useMemo, useState } from 'react'

import type { ConversationItemDto } from '../../core/api/chatGptImportApi'
import { useChatGptImportStore } from '../../core/store/chatGptImportStore'

import { ConversationFilters } from './ConversationFilters'
import { ConversationRow } from './ConversationRow'
import { ImportConfirmDialog } from './ImportConfirmDialog'
import { MultiSelectActionBar } from './MultiSelectActionBar'

interface Props {
  conversations: ConversationItemDto[]
  currentPersonaId: string
  currentPersonaName: string
  personaNames: Record<string, string>
  onConfirmImport: (convs: ConversationItemDto[]) => void
}

export function ConversationList({
  conversations,
  currentPersonaId,
  currentPersonaName,
  personaNames,
  onConfirmImport,
}: Props) {
  const titleSearch = useChatGptImportStore((s) => s.titleSearch)
  const statusFilter = useChatGptImportStore((s) => s.statusFilter)
  const selectedIds = useChatGptImportStore((s) => s.selectedConversationIds)
  const [confirmOpen, setConfirmOpen] = useState(false)

  const filtered = useMemo(() => {
    return conversations.filter((c) => {
      if (
        titleSearch &&
        !c.title.toLowerCase().includes(titleSearch.toLowerCase())
      ) {
        return false
      }
      const inThis = c.imports.some((i) => i.persona_id === currentPersonaId)
      const inAny = c.imports.length > 0
      if (statusFilter === 'not_in_this_persona' && inThis) return false
      if (statusFilter === 'not_in_any_persona' && inAny) return false
      if (statusFilter === 'in_other_persona' && (inThis || !inAny)) return false
      return true
    })
  }, [conversations, titleSearch, statusFilter, currentPersonaId])

  const selectedConvs = conversations.filter((c) =>
    selectedIds.has(c.chatgpt_conversation_id),
  )

  return (
    <div>
      <ConversationFilters />
      {filtered.length === 0 ? (
        <p className="text-center text-white/50 py-12 text-sm">
          No conversations match the current filters.
        </p>
      ) : (
        <div className="divide-y divide-white/5">
          {filtered.map((c) => (
            <ConversationRow
              key={c.chatgpt_conversation_id}
              conv={c}
              currentPersonaId={currentPersonaId}
              personaNames={personaNames}
            />
          ))}
        </div>
      )}
      <MultiSelectActionBar
        onImportClick={() => setConfirmOpen(true)}
        personaName={currentPersonaName}
      />
      <ImportConfirmDialog
        isOpen={confirmOpen}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => {
          setConfirmOpen(false)
          onConfirmImport(selectedConvs)
        }}
        selectedConvs={selectedConvs}
        personaName={currentPersonaName}
        currentPersonaId={currentPersonaId}
      />
    </div>
  )
}
