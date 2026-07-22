# Network Boundaries

## Required policy

Every future tool call and audit event must declare exactly one network scope:

- `LOCAL`: same-host process, filesystem, SQLite, local model, local player, or host-internal Docker call.
- `LAN`: private network device or service outside the host, such as MQTT, Home Assistant, or a future physical AC interface.
- `INTERNET`: public API access. This must pass through Privacy Guard and then the sole `external-connector` egress service.

`external-connector` is the only INTERNET egress service. LOCAL and LAN traffic must not be routed through it.

## Observed topology

```text
companion-private (internal Docker bridge)
  - companion-stepaudio
  - companion-step3-vl-2606
  - companion-app
  - companion-memory
  - companion-orchestrator
  - companion-external-connector

companion-egress (non-internal Docker bridge)
  - companion-external-connector only

companion-local (internal Docker bridge)
  - no attached containers at audit time
```

No inspected companion container published a Docker host port. StepAudio and Step3-VL were reachable by internal Docker DNS from `companion-app`.

## Scope matrix

| Source or destination | Scope | Route requirement | Phase 0 evidence/status |
| --- | --- | --- | --- |
| Local repository and Phase 0 documents | LOCAL | Direct filesystem access | Verified |
| StepAudio via `stepaudio:8010` | LOCAL | Direct on `companion-private`; never via egress connector | Health verified |
| Step3-VL via `step3-vl:8000` | LOCAL | Direct on `companion-private`; never via egress connector | Health verified |
| Local memory service / future SQLite | LOCAL | Direct host/internal service call | Existing service discovered; behavior unverified |
| Local music player | LOCAL | Direct `miniaudio` execution after independent authorization | Phase 4 adapter and allowlisted FLAC asset present |
| AC Mock | LOCAL | Direct Demo-owned function call; reports `模拟执行成功` and no physical action | Implemented in Phase 4 |
| Future physical AC or Home Assistant | LAN | Direct LAN adapter; never via egress connector | Not present and not tested |
| Weather API | INTERNET | Privacy Guard -> `external-connector` -> allowlisted Open-Meteo endpoint | Phase 4 real transport; cache/fixed fallback is explicitly labeled |
| Future public music API | INTERNET | Privacy Guard -> `external-connector` -> allowlisted API | Not present and not tested |

## Existing connector observation

The pre-existing `companion-external-connector` container is the only inspected container attached to both the internal and non-internal companion networks. This topology is compatible with a single egress service, but topology alone does not prove payload filtering or destination allowlisting.

Its OpenAPI also exposes music and AC routes. Route names do not establish whether those requests are LOCAL, LAN, or INTERNET. Before reuse, later contract work must verify that LOCAL music and LOCAL/LAN AC actions do not traverse the INTERNET connector and that no model output can invoke those routes directly.

## Audit and privacy requirements

Future calls must record at least:

```json
{
  "network_scope": "INTERNET",
  "source_agent": "weather_agent",
  "destination": "allowlisted_weather_service",
  "privacy_check": "passed",
  "payload": {
    "city_code": "310000"
  }
}
```

The repository and console must not expose public host addresses, credentials, raw audio, raw video, private memory, or complete external connection details. Phase 0 documentation contains no SSH target, password, token, or private key material.
