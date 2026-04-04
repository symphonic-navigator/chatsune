import { useMemo } from 'react'
import { useParams } from 'react-router-dom'
import { usePersonas } from '../../core/hooks/usePersonas'
import { ChatView } from '../../features/chat/ChatView'

export default function ChatPage() {
  const { personaId } = useParams<{ personaId: string; sessionId?: string }>()
  const { personas } = usePersonas()

  const persona = useMemo(
    () => personas.find((p) => p.id === personaId) ?? null,
    [personas, personaId],
  )

  return <ChatView persona={persona} />
}
