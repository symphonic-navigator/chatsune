# Tentative Barge: Two-Stage Commit for Voice Barge-In

Date: 2026-04-18
Status: Design

## Summary

Replace the current one-shot destructive barge-in with a two-stage commit.
When VAD detects incoming user speech during TTS playback, enter a
**Tentative Barge** state: mute audio output immediately (keeping UX
reactive) but leave the TTS synthesis pipeline, LLM inference, and the
sentence queue untouched. Only once STT returns a non-empty transcript
do we commit to a **Confirmed Barge** and tear everything down as today.
If STT returns empty (the "voice-like" sound was coughing, a door, a
keyboard, or a VAD false positive with sufficient energy to pass the
150 ms misfire window), we resume playback from the sentence anchor that
was active when the barge began.

This eliminates the most common perceived bug of the current live
speech mode: a non-speech noise aborts the assistant's reply for good,
even though nothing was actually said.

## Motivation

Observed repeatedly during live-speech testing:

- The 150 ms VAD misfire deferral (commit `cfd7ea9`) catches short
  bursts but not sustained non-speech energy (steady room noise, a long
  cough, chair creak, keyboard typing). These pass the misfire gate.
- When STT subsequently returns an empty transcript, the assistant's
  turn has already been cancelled:
  - `audioPlayback.stopAll()` tore down the queue
  - `cancelStreamingAutoRead()` killed the sentence synthesis session
  - `cancel_all_for_user()` cancelled the LLM stream on the backend
- The user hears a cut-off sentence followed by silence, despite having
  said nothing.

The fix is to **defer destruction** until the "is this really a barge?"
question is answered by STT, while still muting audio instantly so the
user does not feel the system is talking over them.

## Non-Goals

- No change to the 150 ms misfire deferral; it remains as a first-line
  defence against sub-second bursts. Tentative Barge is a second line
  that handles longer false positives the misfire gate cannot see.
- No per-sentence resume within a sentence. If the user barges mid-word
  at 95 % through a sentence, the entire sentence replays — consistent
  and predictable beats "save a few syllables".
- No hard timeout for STT. Users legitimately speak 15–30 s at a
  stretch; we wait for VAD `speech-end` plus STT completion. The
  existing manual-override button remains the visible affordance that
  the system is still listening.
- No change to backend cancellation semantics on Confirmed Barge.
  `cancel_all_for_user()` is still called; the LLM stream is still
  terminated. The difference is only *when* it happens.
- No persistence of tentative-barge state across reconnects. A
  WebSocket drop during Tentative Barge is treated as a Confirmed Barge
  (conservative fallback).

## Design

### A. State machine

```
IDLE ──(TTS starts)──────────> PLAYING
PLAYING ──(VAD speech-start, 150 ms gate passed)──> TENTATIVE_BARGE
      • audio muted immediately
      • bargeId incremented
      • resume anchor captured (current queue index)
      • TTS synthesis + LLM stream + sentence queue: untouched
TENTATIVE_BARGE ──(VAD speech-end, STT empty, bargeId still current)──> PLAYING
      • resume playback from resume anchor
      • unmute
TENTATIVE_BARGE ──(VAD speech-end, STT non-empty, bargeId still current)──> CONFIRMED_BARGE
      • cancelStreamingAutoRead()
      • audioPlayback.stopAll()
      • backend cancel_all_for_user()
      • onSend(transcript)  → normal chat flow
CONFIRMED_BARGE ──(chat turn ends)──> IDLE
TENTATIVE_BARGE ──(second VAD speech-start, bargeId++)──> TENTATIVE_BARGE
      • anchor kept (earliest anchor wins)
      • any in-flight STT for previous bargeId becomes stale → ignored
PLAYING ──(queue exhausted)──> IDLE
```

The `bargeId` is a monotonically increasing integer kept in the
conversation-mode hook. Any async result (STT promise, VAD callback)
that carries a stale `bargeId` is dropped. This is the core
serialisation guarantee.

### B. Resume anchor

The anchor is the **index into the sentence queue** owned by the
streaming auto-read pipeline at the moment of Tentative Barge. It
points at the sentence that was playing (or about to play if the barge
fell in an inter-sentence gap).

- If playback was mid-sentence when the barge fired: on resume, restart
  that sentence from its beginning (re-enqueue its audio buffer, which
  is still in the cache), then continue with the rest of the queue.
- If playback was between sentences: on resume, start with the next
  queued sentence.
- If the LLM finished during Tentative Barge and new sentences were
  synthesised in the meantime: they are already appended to the queue
  by the existing sentencer logic; resume will play through them
  naturally.

### C. Audio mute vs. stop

Current `audioPlayback.stopAll()` is destructive: it clears the queue
and disconnects the modulation node. Tentative Barge needs a
**non-destructive mute**. Two options:

1. Pause the current `AudioBufferSourceNode` and set output gain to 0.
2. Keep a `mutedAt` timestamp; on resume, re-create the source at the
   sentence anchor and continue.

Option 2 fits the existing architecture better: `AudioBufferSourceNode`
cannot be restarted once stopped, and the SoundTouch modulation chain
already re-instantiates per playback. The mute is therefore "stop the
current source, do not advance the queue, remember the anchor". This
is cheaper than trying to pause in-place and also recovers cleanly
from the sentence-restart requirement in §B.

For the user, the perceived behaviour is identical to a pause: audio
stops immediately on VAD detection.

### D. Backend considerations

The LLM stream on the backend is unaware of the tentative state. It
continues producing content deltas normally. Two outcomes:

- **LLM finishes during Tentative**: `ChatStreamEndedEvent` fires with
  `status="completed"`. The assistant message is committed to history.
  On Confirmed Barge, we do **not** retroactively mark the message as
  aborted — the user heard some of it before the mute, and rewriting
  history to pretend it did not happen is worse UX than leaving the
  (shorter-than-played) message in place. The next turn will include
  it as context.
- **LLM still streaming at Confirmed Barge time**: `cancel_all_for_user()`
  fires as today, producing `status="cancelled"` and the message is
  filtered by `_filter_usable_history()` — unchanged behaviour.

No backend code changes are required for the tentative state itself.
The backend sees the same "cancel now" signal it sees today; it just
arrives a few hundred ms later.

### E. Edge cases

- **Barge just as the last sentence finishes**: queue is empty, anchor
  is `null`, state transitions PLAYING → IDLE between the VAD start
  and its consumption. Treat this as "no resume work to do" on STT-empty:
  simply return to IDLE.
- **Barge during the inter-sentence gap** (configurable gap from
  `2026-04-17-voice-sentence-streaming-design.md`): cancel the pending
  gap-timer; anchor is the next sentence index. On resume, skip the
  remainder of the gap and start the next sentence immediately (the
  mute itself was the gap for the user).
- **Rapid second barge during Resume playback**: the state goes
  PLAYING → TENTATIVE_BARGE again; `bargeId` increments; the **earlier**
  anchor is kept (we want to resume back to where the first barge
  started, not to lose ground every time). If resume has already
  advanced past the original anchor, keep the current queue head as
  the new anchor — never rewind past already-played audio.
- **WebSocket drop during Tentative Barge**: the connection manager
  will mark the session as disconnected. On reconnect, treat any
  unresolved Tentative Barge as Confirmed (cancel everything). This
  is conservative — resuming into a reconnected session risks playing
  stale synthesised audio the user has already mentally moved past.
- **Manual override button pressed during Tentative**: same as today —
  this explicitly tells VAD the user is still speaking, so STT does
  not fire yet. State stays TENTATIVE_BARGE.

## Implementation scope (for later plan)

Only Frontend touches are anticipated. File-level sketch:

- `frontend/src/features/voice/hooks/useConversationMode.ts`: new
  state machine replacing the current `executeBarge` path. Owns
  `bargeId` and the anchor.
- `frontend/src/features/voice/infrastructure/audioPlayback.ts`: add
  a `mute()` / `resumeFrom(anchor)` pair alongside `stopAll()`.
  `stopAll()` remains for Confirmed Barge and normal teardown.
- `frontend/src/features/voice/pipeline/streamingAutoReadControl.ts`:
  expose a `getCurrentAnchor()` read; no change to cancellation.
- No `shared/` or backend changes.

## Testing plan (for later plan)

- Unit: state machine transitions given synthetic VAD/STT event
  sequences, including stale `bargeId` drops.
- Unit: anchor computation across mid-sentence, inter-gap, and
  queue-empty cases.
- Manual: the canonical regression scenarios Chris observed — cough
  during playback, keyboard typing during playback, sustained room
  noise, user barges then actually speaks, user barges twice in quick
  succession.

## Open questions

None at design-freeze time. Any arising during implementation will be
raised back to Chris rather than decided unilaterally.
