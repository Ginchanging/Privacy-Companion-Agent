# Demo Environment Baseline

## Audit scope

- Audit timestamp: 2026-07-20 11:45:24 +08:00.
- Method: read-only inspection over an existing key-authenticated SSH connection.
- Repository baseline: only `AGENTS.md` and root-level `IMPLEMENTATION_PLAN.md` were tracked before Phase 0; the worktree was clean.
- No container, model, service, port, network, device, or startup setting was changed.

## Host resources

| Item | Observed value |
| --- | --- |
| Operating system | Ubuntu 24.04.3 LTS, Linux 6.11.0-1016-nvidia, aarch64 |
| Uptime | 1 week, 5 days, 19 hours, 3 minutes |
| Memory | 119 GiB total, 55 GiB used, 63 GiB available |
| Swap | 15 GiB total, approximately 1.8 MiB used |
| Root disk | ext4, 3.7 TiB total, 1.1 TiB used, 2.5 TiB available (29% used) |
| GPU | NVIDIA GB10, driver 580.95.05, 0% utilization and 36 C at audit time |
| GPU memory reporting | `nvidia-smi` returned `N/A`, consistent with a platform where the queried dedicated-memory fields are unavailable; no capacity value is inferred |
| Docker server | 28.3.3 |

## Running-container baseline

Six containers were running. Restart count was `0` for every container at the initial snapshot.

| Container | Image | Initial state | Started (UTC) | Role classification |
| --- | --- | --- | --- | --- |
| `companion-stepaudio` | `companion-stepaudio:arm64` | healthy | 2026-07-19 06:41:09 | Existing model infrastructure |
| `companion-step3-vl-2606` | `nvcr.io/nvidia/vllm:26.06-py3` | healthy | 2026-07-19 06:37:24 | Existing model infrastructure |
| `companion-app` | `nvcr.io/nvidia/vllm:26.06-py3` | running | 2026-07-17 11:42:21 | Pre-existing companion application service |
| `companion-memory` | `nvcr.io/nvidia/vllm:26.06-py3` | running | 2026-07-17 11:39:48 | Pre-existing companion application service |
| `companion-orchestrator` | `nvcr.io/nvidia/vllm:26.06-py3` | running | 2026-07-17 11:35:27 | Pre-existing companion application service |
| `companion-external-connector` | `nvcr.io/nvidia/vllm:26.06-py3` | running | 2026-07-17 11:31:41 | Pre-existing companion application service |

The four pre-existing application services were not created by this repository during Phase 0. Their ownership and source revision cannot be established from the current local checkout, so they must not be treated as Phase 0 deliverables.

## Docker networks

| Network | Driver | Internal | Attached services |
| --- | --- | --- | --- |
| `companion-private` | bridge | yes | All six running companion containers |
| `companion-egress` | bridge | no | `companion-external-connector` only |
| `companion-local` | bridge | yes | None at audit time |

Docker default `bridge`, `host`, and `none` networks were also present. No network was created, removed, or altered.

## Listening sockets

- All-interface listeners were present on TCP ports 22, 7890, and 9090.
- Loopback-only listeners were present on TCP ports 53, 631, 11000, and 61209.
- The audit did not use elevated privileges and therefore did not attribute every listener to a process.
- None of the inspected companion containers published a Docker host port.

## Camera and local music

- No `/dev/video*` device existed on the host.
- `v4l2-ctl` was not installed.
- No inspected container had an explicit video-device mapping.
- The checked Demo-specific music locations (`/opt/companion-demo/data/music`, `/srv/companion-demo/data/music`, `/data/music`, and `/workspace/data/music`) did not exist.
- `aplay` was available; `ffprobe`, `ffplay`, and `paplay` were unavailable.
- No camera frame, audio file, or video file was opened, captured, played, or copied.

## Baseline conclusion

The DGX Spark has sufficient currently available memory and disk capacity for continued Demo work, subject to later workload testing. Existing model and companion services were running at the initial snapshot. Camera input and a licensed local Demo music asset are not currently available and remain explicit prerequisites for later phases.
