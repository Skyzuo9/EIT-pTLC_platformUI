#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
python3 water_level_8ch_compress_mqtt.py "$@"
