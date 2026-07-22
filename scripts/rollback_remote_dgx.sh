#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: rollback_remote_dgx.sh RELEASE_DIR" >&2
    exit 2
fi

release_dir=$1
project_name=spark-active-companion-demo
cd "$release_dir"

if [ ! -s previous-image.txt ]; then
    echo "this release has no recorded previous image" >&2
    exit 1
fi
previous_image=$(sed -n '1p' previous-image.txt)
case "$previous_image" in
    spark-active-companion-demo:[a-f0-9][a-f0-9]*) ;;
    *) echo "recorded previous image is invalid" >&2; exit 1 ;;
esac

SPARK_DEMO_IMAGE="$previous_image" \
docker compose -p "$project_name" -f docker-compose.dgx.yml up \
    -d --no-build external-connector track-catalog backend

if [ "${SPARK_REMOVE_STEPAUDIO_DEMO_ASSET:-false}" = "true" ]; then
    sh scripts/manage_stepaudio_demo_asset.sh remove
elif [ "${SPARK_REMOVE_STEPAUDIO_DEMO_ASSET:-false}" != "false" ]; then
    echo "SPARK_REMOVE_STEPAUDIO_DEMO_ASSET must be true or false" >&2
    exit 2
fi

printf '%s\n' "ROLLED_BACK_IMAGE=$previous_image"
