# Demo Services and Existing Infrastructure

## Classification

| Service | Classification for this repository | Internal address | Verified health |
| --- | --- | --- | --- |
| StepAudio | Existing model infrastructure; adapter target only | `http://stepaudio:8010` on `companion-private` | HTTP 200 from the service container and HTTP 200 through Docker DNS from `companion-app` |
| Step3-VL | Existing model infrastructure; adapter target only | `http://step3-vl:8000` on `companion-private` | HTTP 200 from the service container and HTTP 200 through Docker DNS from `companion-app` |
| Companion Application | Pre-existing remote application service, not created in Phase 0 | `http://companion-app:8050` on `companion-private` | HTTP 200 |
| Companion Local Memory | Pre-existing remote application service, not created in Phase 0 | `http://companion-memory:8040` on `companion-private` | HTTP 200 |
| Companion Homecoming Scenario | Pre-existing remote application service, not created in Phase 0 | `http://companion-orchestrator:8020` on `companion-private` | HTTP 200 |
| Companion Privacy Connector | Pre-existing remote application service, not created in Phase 0 | `http://companion-external-connector:8030` on `companion-private`; also attached to `companion-egress` | HTTP 200 |

No new Demo runtime service exists in the local Phase 0 checkout. Phase 0 adds documentation only.

## StepAudio interface

- OpenAPI title: `Companion StepAudio`.
- Health: `GET /health`.
- ASR: `POST /v1/audio/transcribe`, `Content-Type: application/json`.
- TTS: `POST /v1/audio/synthesize`, `Content-Type: application/json`.
- Combined response endpoint also present: `POST /v1/respond`.

The Demo adapter uses `/v1/respond` only after deterministic selection of the
highest-confidence state. Its request contains exactly `confirmed_state` and `reply_style`; it never includes
raw audio, a transcript, conversation history, recommendations, authorization,
or actions. The accepted response contains exactly bounded `text`, numeric
`latency_seconds`, and `local_only=true`. StepAudio supplies wording only.

### ASR request

```json
{
  "filename": "synthetic-demo.wav"
}
```

`filename` is required, must contain 1 to 255 characters, and extra fields are rejected. OpenAPI did not document where the named file must be mounted or the structure of the successful JSON response. No transcription request was sent because Phase 0 forbids reading real audio and does not provide a synthetic mounted file.

### TTS request

```json
{
  "text": "Synthetic demo text",
  "voice": "female",
  "max_tokens": 1024
}
```

- `text` is required and limited to 1 to 200 characters.
- `voice` is optional, defaults to `female`, and accepts `female` or `male`.
- `max_tokens` is optional, defaults to 1024, and accepts 256 through 2048.
- Extra fields are rejected.
- OpenAPI reports an `application/json` success response but does not define its schema. No synthesis request was sent.

The container health check uses its loopback `/health` endpoint. Its `/service`, `/model`, and application/runtime mounts were read-only at audit time.

## Step3-VL interface

- Service implementation: vLLM OpenAI-compatible API.
- Served model ID: `step3-vl`.
- Health: `GET /health`.
- Model discovery: `GET /v1/models`.
- Primary request: `POST /v1/chat/completions`, `Content-Type: application/json`.
- `POST /v1/completions`, batch chat, and render endpoints were also exposed.

Minimum text request shape confirmed from OpenAPI:

```json
{
  "model": "step3-vl",
  "messages": [
    {
      "role": "user",
      "content": "Synthetic demo prompt"
    }
  ]
}
```

`messages` is the only required top-level field in the inspected schema; `model` is optional at schema level. User content supports text and referenced image/audio/file content parts. Phase 0 did not expand every multimodal sub-schema and did not submit an inference request.

The current Step3-VL launch configuration enables model-side tool-choice parsing. This is an observed infrastructure setting, not an authorization grant. Future adapters and deterministic policy code must reject any model attempt to authorize or execute an action; Phase 0 did not change the launch configuration.

## Pre-existing application service interfaces

Read-only OpenAPI discovery found:

- Companion Application: `/health`, `/v1/homecoming`.
- Companion Local Memory: `/health`, `/v1/memory/preferences`, `/v1/memory/preferences/{memory_id}`.
- Companion Homecoming Scenario: `/health`, `/v1/scenario/homecoming`.
- Companion Privacy Connector: `/health`, `/v1/weather`, `/v1/music`, `/v1/ac`, `/v1/privacy/audit`.

These routes were discovered but not invoked. Their behavior, privacy enforcement, persistence rules, authorization rules, and source provenance are unverified and must not be assumed compliant merely because health checks pass.

## Verification sample counts

| Check | Samples | Result |
| --- | ---: | --- |
| StepAudio loopback health | 1 | 1/1 HTTP 200 |
| StepAudio Docker-DNS health | 1 | 1/1 HTTP 200 |
| Step3-VL loopback health | 1 | 1/1 HTTP 200 |
| Step3-VL Docker-DNS health | 1 | 1/1 HTTP 200 |
| Each pre-existing application service health | 1 per service, 4 total | 4/4 HTTP 200 |
| OpenAPI retrieval | 6 services | 6/6 HTTP 200 |
| Model discovery | 1 | 1/1 HTTP 200, model ID `step3-vl` |
| ASR, TTS, and model inference | 0 | Intentionally not executed in Phase 0 |
