# MiMo on Novita — tool-call roundtrip rejected (chat-template bug)

**Probed:** 2026-05-12
**Provider:** Novita AI (`https://api.novita.ai/v3/openai/chat/completions`)
**Affected models:** `xiaomimimo/mimo-v2.5-pro`, `xiaomimimo/mimo-v2-flash`
**Status:** Open upstream. Awaiting Novita response.

## Summary

Any request whose `messages` array contains an `assistant` message with a
non-empty `tool_calls` field is rejected with HTTP 400
`invalid_request_error` for the entire `xiaomimimo/*` family on Novita.
The initial tool-call emission works (model can return a `tool_calls`
response), but the continuation turn — which replays that assistant
message followed by the tool result — cannot be parsed by Novita's chat
template for these slugs.

Net effect for downstream clients: **MiMo is effectively unusable with
tools enabled** on Novita today. The first turn produces a tool call,
the second turn (with the tool result) crashes.

## Minimal reproducer

```bash
curl -X POST "https://api.novita.ai/v3/openai/chat/completions" \
  -H "Authorization: Bearer $NOVITA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "xiaomimimo/mimo-v2.5-pro",
    "max_tokens": 200,
    "messages": [
      {"role": "user", "content": "What is the weather in Berlin?"},
      {"role": "assistant", "content": null,
       "tool_calls": [{"id": "call_xyz", "type": "function",
                       "function": {"name": "get_weather",
                                    "arguments": "{\"city\":\"Berlin\"}"}}]},
      {"role": "tool", "tool_call_id": "call_xyz",
       "content": "Sunny, 22°C"}
    ]
  }'
```

Response:

```json
{"message": "invalid request error trace_id: 374755e617bfb55305d9c970f697082c",
 "type": "invalid_request_error"}
```

## Control experiment — identical shape works on DSv4

Same request body, only `"model"` changed to `"deepseek/deepseek-v4-pro"`:

```json
{
  "id": "13279e0f9acf9ec4c1917228b008e93d",
  "model": "deepseek/deepseek-v4-pro",
  "choices": [{"message": {"role": "assistant",
    "content": "The weather in Berlin is currently sunny ...",
    "reasoning_content": "The weather information ..."},
    "finish_reason": "stop"}],
  ...
}
```

This rules out a wire-shape issue on the client side. The OpenAI-compat
shape is correct; the failure is model/template-specific.

## Variants that all fail (probed 2026-05-12)

| Variant | Trace ID | Result |
|---|---|---|
| `content: ""` + `tool_calls` (filled) | `5593fe9866102ba03fbc56e0516a456b` | 400 |
| `content: null` + `tool_calls` (filled) | `e3085e94bfdf8dab2436f387bdb991ce` | 400 |
| Minimal: no reasoning, no `tools` array | `374755e617bfb55305d9c970f697082c` | 400 |
| With `tools` array, no reasoning | `f8301ade78b94e01ee9cde3e18a1e832` | 400 |
| With `reasoning: {enabled: true}` | `ea66c8c2d61701587d6b832564ea2ca5` | 400 |
| `content: "Let me check."` + `tool_calls` | `c8d5eb9365c6910c1c1d32786e099af8` | 400 |
| `tool` message carries `name` field | `2cb443c968de9fb520703cccb0ce1958` | 400 |
| Drop the `tool` message entirely, keep `assistant`+`tool_calls` | `cc970d4b7623c684da7980fa860e3c88` | 400 |
| Replace `tool` message with `user` wrapper | `db6cf7842b01c8548d9bf1dd7bcc5a29` | 400 |
| Same shape against `xiaomimimo/mimo-v2-flash` | `e30fd85b4e5e15e0e8e8ee8332077299` | 400 |

## Variants that succeed

| Variant | Result |
|---|---|
| Drop `tool_calls` from `assistant`, fold tool result as prose user message | ✅ 200 |
| `assistant` with `tool_calls: []` (empty array) | ✅ 200 |
| Single-turn: user → model emits `tool_calls` response | ✅ 200 |

→ The failure is triggered exclusively by a **non-empty `tool_calls`
array on an `assistant` message inside the request `messages` history**.

## Hypothesis

The chat template attached to `xiaomimimo/*` on Novita's serving stack
does not handle the `tool_calls` field on inbound assistant messages —
likely missing a Jinja branch (similar to the canonical
`{% if message.tool_calls %}...{% endif %}` block that vLLM templates
need for tool-roundtrip support).

The fact that **both** `mimo-v2.5-pro` and `mimo-v2-flash` reject the
same shape strongly suggests a shared template, not a model-weights
issue. DSv4 on the same Novita stack accepts the exact same wire shape,
so this is template-specific, not infra-wide.

## Mitigation in Chatsune (downstream)

None applied. Capability spec still reports `tools.supported = true`
because that is the **model's** capability, not Novita's serving stack.
Status quo: users who enable tools with MiMo on Novita will hit this
400 on the second turn. Re-probe quarterly (next: **2026-08-12**) and
flip `tools.supported` to `false` in the driver if still broken at that
point.

Driver: `backend/modules/llm/_drivers/mimo_v25.py` (`MiMoV25Driver`).

## Suggested message to Novita support

> We are seeing reproducible HTTP 400 `invalid_request_error` responses
> from the chat-completions endpoint for the entire `xiaomimimo/*` model
> family (both `mimo-v2.5-pro` and `mimo-v2-flash`) when a request's
> `messages` array contains an `assistant` message with a non-empty
> `tool_calls` array — i.e. on the standard tool-call continuation turn.
>
> The same wire shape succeeds against `deepseek/deepseek-v4-pro` on
> your endpoint, which rules out a client-side payload error.
>
> Reproducer and trace IDs attached. We suspect the chat template
> bundled for these slugs is missing the inbound-`tool_calls` branch
> (the `{% if message.tool_calls %}` block in the OpenAI-compat
> template).
>
> Could you confirm whether the MiMo chat template supports tool-call
> continuation, and if not, escalate to your inference team to add it?
