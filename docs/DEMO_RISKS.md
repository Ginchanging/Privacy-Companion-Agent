# Demo Risks and Open Issues

## High priority

| Risk | Evidence | Required handling |
| --- | --- | --- |
| Camera unavailable | No `/dev/video*`; `v4l2-ctl` unavailable; no container video mapping | Provide an approved camera path or a synthetic/pre-recorded Demo input in a later authorized phase; do not install tools or capture media in Phase 0 |
| Local Demo music unavailable | All checked Demo-specific music directories were absent | Add a licensed synthetic/Demo asset in a later phase; document its license before playback |
| Existing service provenance is unclear | Local checkout contains only project instructions and the implementation plan, while four application containers already run remotely | Treat them as pre-existing services; do not claim they were built or validated by this repository |
| Step3 tool-call capability could cross the authorization boundary | Existing vLLM launch arguments enable automatic tool-choice parsing | Future adapter/schema/policy layers must discard or reject action authorization/execution fields; do not change model startup parameters in Phase 0 |
| Connector boundary requires contract verification | The connector is dual-homed and exposes weather, music, and AC routes | Later contract work must prove INTERNET allowlisting and ensure LOCAL/LAN actions bypass the connector |

## Interface gaps

- StepAudio ASR accepts a `filename`, but OpenAPI does not define the permitted mount/root or successful response schema.
- StepAudio TTS and combined-response endpoints do not define successful response schemas.
- Step3-VL exposes a broad OpenAI-compatible multimodal schema; Phase 0 confirmed the main chat shape but did not freeze the Demo-specific structured output contract.
- Health checks prove reachability only. They do not prove inference quality, authorization safety, privacy filtering, or action behavior.
- No ASR, TTS, Step3 inference, camera capture, music playback, AC operation, or public API request was executed.

## Operational risks

- TCP ports 22, 7890, and 9090 listen on all interfaces. Phase 0 did not use elevated privileges, alter firewall rules, or identify every owning process. The system owner should confirm their intended exposure outside this repository workflow.
- GPU dedicated-memory fields returned `N/A`; capacity planning must use platform-appropriate unified-memory measurements in a later performance phase.
- `ffprobe`, `ffplay`, and `paplay` are unavailable. `aplay` exists, but no audio output or device was tested.
- Existing application containers have no Docker health check status even though their HTTP `/health` endpoints returned 200 once each.
- A password was supplied in the collaboration channel. It was not used, copied into commands, or written to repository files. It should be rotated outside this repository workflow.

## Repository risks

- The instructions refer to `docs/IMPLEMENTATION_PLAN.md`, but the actual tracked plan is root-level `IMPLEMENTATION_PLAN.md`. Phase 0 uses the existing root-level file and does not move or duplicate it.
- There is no application source, Compose file, test suite, camera asset, or music asset in the current checkout. Phase 0 therefore cannot associate the remote application containers with a Git revision.

## Rollback

Phase 0 has no infrastructure rollback because no infrastructure was changed. Repository rollback consists only of removing these newly created files after review:

- `docs/DEMO_BASELINE.md`
- `docs/DEMO_SERVICES.md`
- `docs/NETWORK_BOUNDARIES.md`
- `docs/DEMO_RISKS.md`

Do not use destructive Git reset commands. Remove only the four Phase 0 documents if rollback is explicitly requested.
