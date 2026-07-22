# Phase 5 test, performance, and recovery method

Phase 5 validates repeatability, latency reporting, safe degradation, and restart recovery for the competition Demo only. It does not add product features and it does not restart or modify StepAudio, Step3, their containers, or shared infrastructure.

## Reproducible command

Run the acceptance suite from the repository root after building the console:

```powershell
npm --prefix console run build
python -m scripts.phase5_acceptance --samples 20
```

The command writes the machine-readable result to `reports/phase5/results.json` and the review summary to `reports/phase5/REPORT.md`. Synthetic inputs and temporary SQLite databases are used. Reports reject endpoint URLs, IP addresses, local absolute paths, raw media field names, and credential-like fields.

## Measurement rules

The runner invokes each of the ten interfaces listed in the implementation plan exactly `--samples` times. Values below 20 are rejected. It records elapsed time with `time.perf_counter_ns()` and reports milliseconds to three decimal places.

`count`, success and failure counts, rate, minimum, maximum, mean, P50, and P95 are calculated over all attempts, including failed calls. P50 and P95 use the nearest-rank method and are emitted only when at least 20 samples exist. A failed real model or weather call remains a failed sample; it is never relabelled as a Mock success.

Real Step3, real ASR, and real weather are availability observations with a minimum success threshold of zero because the runner cannot safely repair or restart external/shared services. Their table result is `MEASURED`, not `PASS`, and their exact failure counts remain visible. Acceptance of model unavailability is instead gated by the separate 5/5 degraded E2E scenario.

The Music Executor benchmark starts the real LOCAL `miniaudio` playback backend with the repository's synthetic Demo asset. This proves that the local software playback path accepted the action. It does not prove that a person heard sound or that any external physical device acted. AC remains explicitly Mock-only and records `physical_action_performed=false`.

## End-to-end and faults

Two five-run acceptance modes are required:

- fixed Mock Demo, using separate music and AC action IDs and authorizations;
- model-unavailable degraded Demo, using synthetic camera observation, text fallback, rule fallback, a recording playback test double, synthetic weather transport, and AC Mock.

Every run checks deterministic highest-confidence state selection, memory retrieval,
privacy-audited internet routing, both independent action authorizations, audit
events, and the terminal state. Both modes require exactly 5/5; 4/5 fails.

The fault matrix covers camera, ASR, Step3 timeout and invalid schema, weather API, unavailable connector, delayed TTS, SQLite, Privacy Guard, music, AC Mock, expired authorization, mismatched action ID, and duplicate execution.

## Recovery boundary

Recovery uses two short-lived Python processes and one temporary SQLite database. The first process starts the ASGI lifespan and seeds pending, approved, expired, running, and completed actions. The second process starts a fresh ASGI lifespan and verifies state coordination, console asset reload, and connector recreation.

No recovered action enters an executor. Pending remains pending, valid approved remains not started, expired approved becomes expired, interrupted running becomes failed with `INTERRUPTED_BY_RESTART`, and the completed action remains terminal. Existing model restart recovery is recorded as `NOT_RUN_NO_AUTHORIZATION`, as required by the maintenance-window rule.
