#!/bin/sh
set -eu

mode=${1:-}
case "$mode" in
    install|remove) ;;
    *) echo "usage: manage_stepaudio_demo_asset.sh install|remove" >&2; exit 2 ;;
esac

asset_name=spark_today_tired_zh_cn.wav
expected_sha256=e067ab69526c6470a461cad3d93f3d72756c34ef14fa33b58af07807840d36d6
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
release_dir=$(dirname -- "$script_dir")
source_asset=$release_dir/assets/stepaudio/$asset_name

if [ ! -f "$source_asset" ]; then
    echo "synthetic StepAudio asset is missing from the release" >&2
    exit 1
fi
source_sha256=$(sha256sum "$source_asset" | awk '{print $1}')
if [ "$source_sha256" != "$expected_sha256" ]; then
    echo "synthetic StepAudio asset hash does not match the manifest" >&2
    exit 1
fi

containers=$(docker ps --filter name=companion-stepaudio --format '{{.Names}}')
container_count=$(printf '%s\n' "$containers" | awk 'NF { count += 1 } END { print count + 0 }')
if [ "$container_count" -ne 1 ]; then
    echo "exactly one running StepAudio container is required" >&2
    exit 1
fi
container_name=$(printf '%s\n' "$containers" | awk 'NF { print; exit }')
mount=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/app/assets"}}{{.Type}}|{{.Source}}|assets{{end}}{{end}}' "$container_name")
if [ -z "$mount" ]; then
    mount=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/app"}}{{.Type}}|{{.Source}}|app{{end}}{{end}}' "$container_name")
fi
mount_type=$(printf '%s' "$mount" | cut -d '|' -f 1)
mount_source=$(printf '%s' "$mount" | cut -d '|' -f 2)
mount_layout=$(printf '%s' "$mount" | cut -d '|' -f 3)
if [ "$mount_type" != "bind" ] || [ -z "$mount_source" ]; then
    echo "StepAudio /app/assets is not backed by the /app/assets or /app host bind" >&2
    exit 1
fi
if [ "$mount_layout" = "app" ]; then
    mount_source=$mount_source/assets
fi
if [ ! -d "$mount_source" ] || [ ! -w "$mount_source" ]; then
    echo "StepAudio asset host directory is not writable; sudo is forbidden" >&2
    exit 1
fi
resolved_mount=$(realpath "$mount_source")
destination=$resolved_mount/$asset_name
if [ "$(dirname -- "$destination")" != "$resolved_mount" ]; then
    echo "resolved asset destination escaped the StepAudio bind directory" >&2
    exit 1
fi

if [ "$mode" = "remove" ]; then
    if [ ! -e "$destination" ]; then
        echo "synthetic StepAudio asset is already absent"
        exit 0
    fi
    installed_sha256=$(sha256sum "$destination" | awk '{print $1}')
    if [ "$installed_sha256" != "$expected_sha256" ]; then
        echo "refusing to remove an asset whose hash differs" >&2
        exit 1
    fi
    rm -f -- "$destination"
    echo "removed the hash-matched synthetic StepAudio asset; the release copy remains recoverable"
    exit 0
fi

if [ -e "$destination" ]; then
    installed_sha256=$(sha256sum "$destination" | awk '{print $1}')
    if [ "$installed_sha256" != "$expected_sha256" ]; then
        echo "refusing to overwrite an existing StepAudio asset with a different hash" >&2
        exit 1
    fi
    echo "synthetic StepAudio asset already installed with the expected hash"
    exit 0
fi

temporary=$(mktemp "$resolved_mount/.spark-stepaudio-asset.XXXXXX")
cleanup() {
    rm -f -- "$temporary"
}
trap cleanup EXIT HUP INT TERM
cp -- "$source_asset" "$temporary"
temporary_sha256=$(sha256sum "$temporary" | awk '{print $1}')
if [ "$temporary_sha256" != "$expected_sha256" ]; then
    echo "copied synthetic StepAudio asset failed hash verification" >&2
    exit 1
fi
chmod 0444 "$temporary"
if ! ln "$temporary" "$destination"; then
    if [ -e "$destination" ] && [ "$(sha256sum "$destination" | awk '{print $1}')" = "$expected_sha256" ]; then
        echo "synthetic StepAudio asset was installed concurrently with the expected hash"
        exit 0
    fi
    echo "failed to install synthetic StepAudio asset without overwriting" >&2
    exit 1
fi
echo "installed one hash-verified synthetic StepAudio asset without restarting the container"
