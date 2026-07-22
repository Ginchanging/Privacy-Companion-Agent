# Emotion Reaction and Privacy-Safe Memory

This Demo keeps Step3 advisory. It does not modify the Step3 or StepAudio
containers and does not add another model service.

## Text flow

1. `POST /v1/analysis/text` calls the existing LOCAL Step3 service for strict
   nine-state classification and a bounded reaction.
2. Shanghai outdoor weather is obtained only through `external-connector` and
   is marked `REAL_API`, `CACHE`, or `FIXED_DEMO`.
3. The five-minute, single-use `analysis_id` is continued through
   `POST /v1/analysis/text/{analysis_id}/sessions`. The backend selects the
   highest-confidence state and immediately prepares the reply and deterministic
   policy result. Original text is not sent again.
4. The former `state-confirmation` route returns HTTP 409
   `STATE_CONFIRMATION_DISABLED`; new sessions do not pause for emotional-state
   clarification.
5. Any music and AC proposals still use different `action_id` values and require
   separate, explicit user authorization.

Removing emotional-state clarification does not grant the model execution
authority. Step3 output with tool calls, authorization, execution, confirmation
bypass, or memory-write instructions is rejected.

## Deterministic action policy

- A confirmed `music_preference=NONE` rejects the music suggestion.
- AC requires weather from `REAL_API` or `CACHE`; `FIXED_DEMO` is ineligible.
- At or below 12°C, only `WARMER` creates `heat / 24°C / 30 minutes`.
- At or above 30°C, only `COOLER` creates `cool / 26°C / 30 minutes`.
- Other temperatures and direction mismatches are rejected with a visible reason.
- Zero accepted suggestions completes the reaction without an Action. Accepted
  suggestions enter only their corresponding authorization states.

AC remains a Mock and must never be described as a physical action.

## Persistence and privacy

SQLite stores confirmed user preferences and retains only the newest 50 emotion
summaries. A summary contains IDs, selected label, confidence band, reaction
tone, music/AC outcomes, and a timestamp. Model context reads counts and the five
most recent labels.

SQLite does not store original text, evidence, reply text, reasons, raw model
output, complete weather responses, audio, or video.

Management endpoints:

- `GET /v1/user-preferences`
- `POST /v1/user-preferences/confirm`
- `DELETE /v1/user-preferences/{reply_style|music_preference}`
- `GET /v1/emotion-summaries`
- `DELETE /v1/emotion-summaries`

## Optional TTS

`POST /v1/analysis/sessions/{session_id}/tts` is user initiated. It makes one
LOCAL StepAudio request with a 120-second upper bound and a 2 MiB response limit.
A valid `audio/wav` response is proxied with `Cache-Control: no-store` for
temporary browser playback. Invalid content, malformed/oversized WAV, timeouts,
and upstream errors return `TEXT_ONLY`; text remains available. Synthesized
audio is not written to disk, SQLite, or audit payloads.
