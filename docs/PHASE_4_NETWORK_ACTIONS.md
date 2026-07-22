# Phase 4 weather and LOCAL action boundaries

Phase 4 adds one real INTERNET capability and one real LOCAL capability without changing the Step3 authorization boundary.

## Weather

The backend creates exactly this connector request payload:

```json
{"city_code":"310000"}
```

Privacy Guard validates it before `external_connector.weather.RealExternalConnector` maps the fixed Shanghai city code to fixed coordinates. Only that module can contact `https://api.open-meteo.com/v1/forecast`; redirects, alternate hosts, responses over 1 MiB, and malformed values are rejected.

The fallback order is `REAL_API -> CACHE -> FIXED_DEMO`. SQLite stores only normalized temperature, condition, provider, city code, and `fetched_at`. The console always displays the selected source. Weather data attribution: Open-Meteo.com.

## Music

LIVE and text-analysis sessions prepare browser audio only after independent
authorization. The logical player command remains exactly:

```json
{"action":"play","track_id":"calm_piano_01"}
```

The deterministic policy and delivery layer both verify the independent action
ID, APPROVED status, expiry, and duplicate execution. Audius previews remain
bounded to 8 MiB; the local fallback uses a separately hashed 30-second browser
derivative under the same Demo authorization. Audio stays in memory, is returned
with `Cache-Control: no-store`, and is never written to SQLite. The Action
becomes `SUCCEEDED` only after the Windows browser reports a real `playing`
event. That report does not prove that a person heard the audio. Mock sessions
remain deterministic and do not play audio.

The repository owner confirmed the existing track may be used in this competition Demo. No external license source was supplied, so the repository does not claim one.

## AC Mock and audit

AC remains a LOCAL Mock. Success is always labeled `模拟执行成功`, `mock=true`, and `physical_action_performed=false`. LAN is a future boundary and is never invoked in Phase 4.

The console consumes backend events for INTERNET weather, LOCAL browser delivery,
and LOCAL AC Mock. It displays the real connector/player payloads, identifies the
SSH loopback delivery, and marks LAN as `NOT INVOKED`.

## Run

Install `requirements.txt`, start the existing ASGI application, and open
`/console/` through the SSH loopback tunnel. Starting the LIVE chain may call
Open-Meteo. Music is fetched only after its own approval; if browser autoplay is
blocked, the Action remains unexecuted until the user clicks play. AC still
requires a separate approval.

Do not report audible playback unless a person at the machine confirms it. Do not report fallback weather as a successful real API response.
