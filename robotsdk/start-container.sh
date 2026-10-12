#!/bin/bash
set -euo pipefail
if ! docker inspect robotsdk >/dev/null 2>&1; then
    echo 'robotsdk container is not created; use create-container.sh' >&2
    exit 1
fi
if [[ $(docker inspect -f '{{.State.Running}}' robotsdk) != true ]]; then
    docker start robotsdk
fi
echo 'robotsdk is running (starting the container does NOT start or enable motors).'
