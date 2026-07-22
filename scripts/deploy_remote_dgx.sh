#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
    echo "usage: deploy_remote_dgx.sh IMAGE_TAG RELEASE_DIR" >&2
    exit 2
fi

image_tag=$1
release_dir=$2
project_name=spark-active-companion-demo

case "$image_tag" in
    spark-active-companion-demo:[a-f0-9][a-f0-9]*) ;;
    *) echo "invalid image tag" >&2; exit 2 ;;
esac
cd "$release_dir"

compose_files="-f docker-compose.dgx.yml"
audius_config_dir=
audius_secrets_dir=
existing_connector=$(docker ps \
    --filter "label=com.docker.compose.project=$project_name" \
    --filter label=com.docker.compose.service=external-connector \
    --quiet | head -n 1)
if [ -n "$existing_connector" ]; then
    audius_config_dir=$(docker inspect --format \
        '{{range .Mounts}}{{if eq .Destination "/run/config"}}{{.Source}}{{end}}{{end}}' \
        "$existing_connector")
    audius_secrets_dir=$(docker inspect --format \
        '{{range .Mounts}}{{if eq .Destination "/run/secrets"}}{{.Source}}{{end}}{{end}}' \
        "$existing_connector")
fi
if [ -n "$audius_config_dir" ] || [ -n "$audius_secrets_dir" ]; then
    if [ -z "$audius_config_dir" ] || [ -z "$audius_secrets_dir" ]; then
        echo "refusing to deploy with a partial Audius read-only mount" >&2
        exit 1
    fi
    case "$audius_config_dir:$audius_secrets_dir" in
        /*:/*) ;;
        *) echo "Audius mount sources must be absolute directories" >&2; exit 1 ;;
    esac
    if [ ! -d "$audius_config_dir" ] || [ ! -d "$audius_secrets_dir" ]; then
        echo "existing Audius mount source is unavailable" >&2
        exit 1
    fi
    export SPARK_AUDIUS_CONFIG_DIR="$audius_config_dir"
    export SPARK_AUDIUS_SECRETS_DIR="$audius_secrets_dir"
    compose_files="$compose_files -f docker-compose.dgx.audius.yml"
fi
export SPARK_DEMO_IMAGE="$image_tag"

compose() {
    # compose_files contains only repository-owned fixed filenames.
    # shellcheck disable=SC2086
    docker compose -p "$project_name" $compose_files "$@"
}

model_state() {
    for pattern in companion-stepaudio companion-step3-vl; do
        container_name=$(docker ps --filter "name=$pattern" --format '{{.Names}}' | head -n 1)
        if [ -z "$container_name" ]; then
            echo "required model container is unavailable: $pattern" >&2
            return 1
        fi
        docker inspect \
            --format '{{.Name}}|{{.Id}}|{{.State.StartedAt}}|{{.RestartCount}}' \
            "$container_name"
    done
}

model_state > model-state-before.txt

compose config --quiet

docker build --target test -t "${image_tag}-test" .
docker run --rm --network none "${image_tag}-test"
docker build --target runtime -t "$image_tag" .

if [ "${SPARK_INSTALL_STEPAUDIO_DEMO_ASSET:-false}" = "true" ]; then
    sh scripts/manage_stepaudio_demo_asset.sh install
elif [ "${SPARK_INSTALL_STEPAUDIO_DEMO_ASSET:-false}" != "false" ]; then
    echo "SPARK_INSTALL_STEPAUDIO_DEMO_ASSET must be true or false" >&2
    exit 2
fi

existing_backend=$(compose ps -q backend 2>/dev/null || true)
if [ -n "$existing_backend" ]; then
    docker inspect --format '{{.Config.Image}}' "$existing_backend" > previous-image.txt
fi

compose up \
    -d --no-build external-connector track-catalog backend

attempt=0
backend_id=$(compose ps -q backend)
until docker exec "$backend_id" python - <<'PY'
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2) as response:
    if response.status != 200:
        raise SystemExit(1)
PY
do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 30 ]; then
        echo "backend container health did not become ready" >&2
        exit 1
    fi
    sleep 2
done

model_state > model-state-after.txt
if ! cmp -s model-state-before.txt model-state-after.txt; then
    echo "existing model container state changed during deployment" >&2
    exit 1
fi

SPARK_DEMO_IMAGE="$image_tag" \
python3 scripts/verify_dgx_deployment.py \
    --compose-file docker-compose.dgx.yml \
    --project "$project_name" \
    > deployment-verification.json

printf '%s\n' "$image_tag" > deployed-image.txt
printf '%s\n' "DEPLOYED_IMAGE=$image_tag"
if [ -n "$audius_config_dir" ]; then
    printf '%s\n' "AUDIUS_CONFIGURATION=PRESERVED_READ_ONLY"
else
    printf '%s\n' "AUDIUS_CONFIGURATION=NOT_CONFIGURED"
fi
printf '%s\n' "REMOTE_PUBLISHED_PORT=NONE"
printf '%s\n' "VERIFICATION=$release_dir/deployment-verification.json"
