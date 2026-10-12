#!/bin/bash
set -euo pipefail
/home/nvidia/robotsdk/start-container.sh
exec docker exec -it -w /workspace robotsdk bash --rcfile /workspace/env.sh -i
