# DGX Spark backend deployment

This runbook deploys only this repository's Demo-owned backend, Track Catalog,
and external-connector. Existing Step3 and StepAudio containers are reused through
their existing HTTP interfaces and are never stopped, restarted, rebuilt, or
reconfigured.

## Runtime topology

```text
local browser
  -> SSH loopback tunnel
  -> DGX Demo-private container address
  -> backend:8000 (no published host port)
       -> companion-private -> stepaudio:8010 / step3-vl:8000
       -> demo-private -> track-catalog:8011
       -> demo-private -> external-connector:8030 -> demo-egress -> INTERNET
```

The backend and Track Catalog have no egress network. The external-connector is
the only member of the new Demo egress network. No Demo container publishes a
host port. The local SSH client resolves the running backend's Demo-private
address and binds only local `127.0.0.1`; no DGX LAN or public listener is
created. Browser HTTP and WebSocket traffic remain same-origin, so CORS is not
enabled.

## Prerequisites

- The local machine has an existing non-interactive SSH config alias for DGX Spark.
- The SSH user can run Docker and Docker Compose without `sudo`.
- Existing Docker network `companion-private` contains healthy aliases
  `stepaudio` and `step3-vl`.
- Local port `8000` is available.

Never put the SSH host, IP, key, Audius credentials, or a real `.env` in this
repository or command logs.

## Deploy the current workspace snapshot

From the local repository:

```powershell
$SparkSshAlias = "your-existing-dgx-ssh-alias"
.\scripts\deploy_dgx_spark.ps1 `
  -SshAlias $SparkSshAlias `
  -InstallStepAudioDemoAsset
```

`-InstallStepAudioDemoAsset` is the explicit opt-in for the single registered
synthetic WAV. The helper discovers the existing StepAudio `/app/assets` host
bind, requires it to be writable without `sudo`, and refuses to overwrite an
existing different hash. It changes no model code, weights, startup parameters,
ports, or container lifecycle. Omitting the switch leaves the asset untouched
and the fixed text fallback remains available.

The script copies an explicit allowlist of current source files. It rejects and
excludes Git metadata, `.env` files, private SQLite databases, local Audius
configuration, credentials, runs, `node_modules`, caches, unapproved/private media, and model
weights. The locally verified console build in `console/dist` is included in the
allowlist. The archive SHA256 becomes the release directory and image tag.

The ARM64 application image reuses the NVIDIA vLLM runtime already cached on the
DGX (`nvcr.io/nvidia/vllm:26.06-py3`) and installs only the fixed `miniaudio`
package required by the complete test suite and optional audio validation. It
does not start another model server, copy model weights, or change the existing
Step3/StepAudio runtime parameters. This also avoids relying on Docker Hub during
an isolated competition deployment.

On DGX it performs, in order:

1. Record the existing Step3 and StepAudio container IDs, start timestamps, and
   restart counts.
2. Validate Compose configuration.
3. Build and run the ARM64 test image with no network.
4. Build the runtime image.
5. If explicitly enabled, install the one hash-verified synthetic WAV into the
   existing StepAudio asset bind without restarting it.
6. Start only the three Demo-owned services.
7. Verify the absence of published ports, network membership, service health, and unchanged
   model container state.

No `docker compose down`, prune, model restart, host restart, or volume deletion
is performed.

## Open the console locally

```powershell
$Tunnel = .\scripts\start_dgx_console_tunnel.ps1 -SshAlias $SparkSshAlias
$Tunnel
```

Open the returned URL, normally:

```text
http://127.0.0.1:8000/console/
```

The console's deployment health must display `DGX_SPARK · SSH_LOOPBACK`.
`STEP3` and `STEPAUDIO` health only prove reachability; inference and TTS success
must be supported by their actual synthetic request results.

Stop only this tunnel with its returned process ID:

```powershell
Stop-Process -Id $Tunnel.process_id
```

## Synthetic runtime acceptance

After deployment, run this inside the versioned release on DGX. Resolve the
backend address from Docker state rather than publishing a host port:

```sh
backend_id=$(docker ps \
  --filter label=com.docker.compose.project=spark-active-companion-demo \
  --filter label=com.docker.compose.service=backend \
  --quiet)
backend_ip=$(docker inspect \
  --format '{{with index .NetworkSettings.Networks "spark-active-companion-demo_demo-private"}}{{.IPAddress}}{{end}}' \
  "$backend_id")
python3 scripts/dgx_runtime_acceptance.py \
  --base-url "http://$backend_ip:8000" \
  --samples 20
```

This sends synthetic text only. It does not authorize actions, play audio, access
a camera, or claim that a person heard sound. P95 is reported only for interfaces
that actually ran at least 20 samples. StepAudio synthesis permits up to 120
seconds per model call; the backend performs it off the ASGI event loop so health
and console event requests remain responsive while text is already visible.

The DGX Compose deployment sets `SPARK_MUSIC_PLAYBACK_TARGET=BROWSER`. It does
not map `/dev/snd` or open a DGX audio device. After music authorization, bounded
audio is returned through the existing SSH loopback request and played by the
Windows browser. No additional host or public port is required.

## Audius enablement and preservation

Without the optional override, Audius is `NOT_CONFIGURED` and music falls back to
the repository-owned procedural WAV. That fallback must not be reported as a real
Audius fetch. Weather remains available through the isolated connector.

To enable Audius, a DGX administrator places credentials in two plain-text files
and an approved `audius_playlists.local.json` in separate absolute directories
outside the release tree. `docker-compose.dgx.audius.yml` receives only those
directory paths through `SPARK_AUDIUS_CONFIG_DIR` and
`SPARK_AUDIUS_SECRETS_DIR`; the files are mounted read-only into
external-connector and are never mounted into backend or sent to the browser.

After Audius has been enabled once, `deploy_remote_dgx.sh` discovers the two
existing read-only mount sources and preserves them during upgrades. It refuses a
partial or unavailable mount instead of silently disabling the provider. Runtime
success still depends on public preview availability and browser playback; a
local fallback or automated media event is not human listening acceptance.

## Rollback

Every successful replacement records the previous Demo image in the new release.
Rollback requires the release ID printed by deployment:

```powershell
.\scripts\rollback_dgx_spark.ps1 `
  -SshAlias $SparkSshAlias `
  -ReleaseId "0123456789abcdef"
```

Rollback recreates only the three Demo-owned services with the previous image.
It does not remove volumes or releases and does not target Step3 or StepAudio.
The synthetic asset is retained by default. To remove it as part of rollback,
add `-RemoveStepAudioDemoAsset`; deletion occurs only if its current SHA-256 still
matches the manifest, so a changed or unrelated file is never removed.
