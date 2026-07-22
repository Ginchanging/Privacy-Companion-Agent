# Phase 4 Console

This React/Vite console is a local surface for the repository's Demo backend.
The browser does not call models, devices, or public APIs directly.

```powershell
cd console
npm ci
npm run test -- --run
npm run build
cd ..
python -m uvicorn backend.app.api:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/console/`. The built assets are served by the same
ASGI application as the Demo API and WebSocket. All execution results shown by
the page distinguishes real LOCAL music playback from the AC Mock result.

The **启动真实 / 降级链** control uses the Phase 3 `/v1/live` adapters. When a
camera or existing LOCAL model service is unavailable, the page displays the exact
fallback source and reason. Runtime configuration and privacy constraints are in
`docs/PHASE_3_ADAPTERS.md`.

Phase 4 LIVE mode shows Open-Meteo/cache/fixed weather provenance, the exact
INTERNET connector payload, and the exact LOCAL music payload. AC always remains
a clearly labeled Mock; LAN is displayed only as a future, uninvoked boundary.
See `docs/PHASE_4_NETWORK_ACTIONS.md`.
