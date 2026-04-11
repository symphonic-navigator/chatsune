/* clientToolHandler.ts — bridges the WebSocket event bus to the
 * sandbox host. Registered once at app startup; the returned cleanup
 * function is the unsubscribe callback supplied by eventBus.on.
 */

import type { BaseEvent } from '../../core/types/events'
import { eventBus } from '../../core/websocket/eventBus'
import { sendMessage } from '../../core/websocket/connection'
import { runSandbox } from './sandboxHost'

const MAX_OUTPUT_BYTES = 4096

interface DispatchPayload {
  session_id: string
  tool_call_id: string
  tool_name: string
  arguments: { code?: string } & Record<string, unknown>
  timeout_ms: number
  target_connection_id: string
}

function sendResult(
  toolCallId: string,
  result: { stdout: string; error: string | null },
): void {
  sendMessage({
    type: 'chat.client_tool.result',
    tool_call_id: toolCallId,
    result,
  })
}

export function registerClientToolHandler(): () => void {
  return eventBus.on('chat.client_tool.dispatch', (event: BaseEvent) => {
    // eventBus callbacks are sync — we start the async work but do not
    // await it here. The handler sends the result via sendMessage when
    // the sandbox resolves.
    void handleDispatch(event.payload as unknown as DispatchPayload)
  })
}

async function handleDispatch(ev: DispatchPayload): Promise<void> {
  if (ev.tool_name !== 'calculate_js') {
    sendResult(ev.tool_call_id, {
      stdout: '',
      error: `Unknown client tool: ${ev.tool_name}`,
    })
    return
  }

  const code = typeof ev.arguments?.code === 'string' ? ev.arguments.code : ''
  if (!code) {
    sendResult(ev.tool_call_id, { stdout: '', error: 'No code provided' })
    return
  }

  try {
    const result = await runSandbox(code, ev.timeout_ms, MAX_OUTPUT_BYTES)
    sendResult(ev.tool_call_id, result)
  } catch (e) {
    sendResult(ev.tool_call_id, {
      stdout: '',
      error: `Sandbox host crashed: ${e instanceof Error ? e.message : String(e)}`,
    })
  }
}
