import type { ConversationItemDto } from '../../core/api/chatGptImportApi'

interface Props {
  conv: ConversationItemDto
}

/**
 * Expanded preview for a conversation row — shows the first user and
 * assistant message bodies that the parser captured. The backend caps each
 * preview at 200 characters; the full text only becomes available once the
 * conversation is imported into a real Chatsune session.
 */
export function ConversationPreviewExpanded({ conv }: Props) {
  return (
    <div className="ml-8 mt-2 pl-3 border-l-2 border-white/10 text-sm text-white/70 space-y-2">
      {conv.first_user_message_preview && (
        <div>
          <span className="font-mono text-xs px-1 py-0.5 bg-white/10 rounded mr-2">
            user
          </span>
          {conv.first_user_message_preview}
          {conv.first_user_message_preview.length >= 200 && (
            <span className="text-white/40 italic"> … (truncated)</span>
          )}
        </div>
      )}
      {conv.first_assistant_message_preview && (
        <div>
          <span className="font-mono text-xs px-1 py-0.5 bg-white/10 rounded mr-2">
            assistant
          </span>
          {conv.first_assistant_message_preview}
          {conv.first_assistant_message_preview.length >= 200 && (
            <span className="text-white/40 italic"> … (truncated)</span>
          )}
        </div>
      )}
      <p className="text-xs text-white/40 italic">
        Full message list is available once imported into a session.
      </p>
    </div>
  )
}
