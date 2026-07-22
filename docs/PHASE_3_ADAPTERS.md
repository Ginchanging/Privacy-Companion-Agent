# Phase 3 Adapter Runtime

Phase 3 adds a `LIVE` pipeline without changing the existing `/v1/mock` API.
Model and media calls are LOCAL only. Music and AC execution remain explicit Mock
results in this phase and never claim physical execution.

## Step3 Demo-image visual perception

The console offers two fixed Demo scenes: one indoor person scene and one
matching empty scene. Tests and default local development use repository-owned
synthetic PNG files. The DGX deployment may select authorized, Git-ignored,
locally compressed JPEG copies with `SPARK_DEMO_SCENE_MEDIA=private`. The browser
submits only the allowlisted `scene_id`; the backend reads the matching image and
sends it to the existing DGX `step3-vl` service over the LOCAL model network.

The model may return only `person_present`, `scene_type`, a bounded scene
summary, uncalibrated confidence, and bounded evidence. Identity, emotion,
sensitive traits, recommendations, authorization, execution, tool calls, and
memory writes are outside this contract. Invalid or unavailable model output
returns HTTP 503 and leaves the current session unchanged; fixture labels are
never used as a runtime fallback.

When Step3 confirms a person, the backend creates or reuses one LIVE session and
waits for the explicit fixed-speech control. It does not start StepAudio merely
because a person was detected. An empty
scene creates no session, or closes the active Demo-image LIVE session.
Raw image bytes, data URLs, raw model requests, and raw model responses are not
written to SQLite or audit Payloads.

## Non-secret configuration

The default ASGI application reads only these optional environment variables:

| Variable | Default | Constraint |
| --- | --- | --- |
| `SPARK_STEPAUDIO_URL` | `http://stepaudio:8010` | Allowlisted internal hostname, loopback, or private IP; HTTP only |
| `SPARK_STEP3_URL` | `http://step3-vl:8000` | Allowlisted internal hostname, loopback, or private IP; HTTP only |
| `SPARK_DEMO_SCENE_MEDIA` | `synthetic` | `synthetic` for repository fixtures or `private` for authorized, Git-ignored JPEG copies |
| `SPARK_STEPAUDIO_FILENAME` | `spark_today_tired_zh_cn.wav` | Fixed repository-owned synthetic WAV basename; the browser cannot supply a path |
| `SPARK_CAMERA_INDEX` | `0` | Non-negative integer |
| `SPARK_DEMO_VIDEO_PATH` | unset | File beneath `data/demo_inputs/` only |

Do not place real user audio or video in `data/demo_inputs/`. The directory is
Git-ignored. Do not put credentials in these variables or print the process
environment in completion evidence.

## Runtime behavior

- The console polls lightweight perception once per second. Two consecutive
  observations confirm appearance or departure.
- Vision tries Camera, then an approved Demo video, then an in-memory synthetic
  static scene. Every fallback is visible in the Session and audit timeline.
- `POST /v1/live/sessions/{session_id}/speech-demo` accepts an empty object only;
  the backend selects the fixed synthetic asset. It never reads a microphone or
  accepts a browser-supplied filename.
- If StepAudio cannot transcribe the configured synthetic file, the Session stays
  in `LISTENING` and accepts only the fixed text fallback `今天有点累`.
- Step3 responses are rejected if they contain tool calls, forbidden execution or
  authorization fields, invalid JSON, or data outside the strict schema. The
  deterministic rule candidate then continues through the existing Policy Engine.
- Before Step3 returns a valid state there is no assistant reply, Action, or TTS
  call. The backend then selects the highest-confidence state without a separate
  clarification step. `/v1/respond` receives only that selected state and bounded
  reply style. StepAudio supplies wording only; it cannot determine
  state, recommend an Action, authorize, or execute.
- TTS is text-first. LIVE TTS returns bounded `audio/wav` with
  `Cache-Control: no-store`; the Windows browser attempts playback and reports
  `STARTED` only from the `playing` event. Autoplay blocking exposes a manual
  play button. Refresh never regenerates or replays speech automatically.
- Raw frames, audio, model requests, and model responses are never written to
  SQLite or audit Payloads. Adapter audit events store only bounded metadata and
  latency.

The polling behavior above remains available for the older camera/video adapter
contract. The primary console uses the explicit synthetic-scene endpoint and
does not claim that a camera is active.

## Current verification boundary

The development machine used for Phase 3 cannot resolve the internal model DNS
names and has no confirmed camera. Automated acceptance therefore uses synthetic
sources and fake LOCAL transports. Real camera, StepAudio, and Step3 results must
not be claimed until the same tests are executed from the existing internal model
network with approved synthetic media. Automated playback events prove only
browser media state, never that a person heard the sound.

## Fixed synthetic asset deployment

The only allowed ASR asset is registered in `assets/stepaudio/manifest.json`.
Deployment is disabled by default. To install it, pass
`-InstallStepAudioDemoAsset` to `scripts/deploy_dgx_spark.ps1`. The remote helper
requires exactly one running StepAudio container and an existing writable bind
mount at `/app/assets`; it verifies the source SHA-256, refuses a different
same-name file, never invokes `sudo`, and does not stop, restart, or modify the
model container.

Rollback keeps the asset by default. Pass `-RemoveStepAudioDemoAsset` to the
rollback script only when removal is intended. Removal proceeds only when the
installed file still matches the registered SHA-256; the release copy remains
available for recovery.
