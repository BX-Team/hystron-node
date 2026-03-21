#!/usr/bin/env bash
set -euo pipefail

echo "hystron-node starting..."
echo "  xray config: ${XRAY_CONFIG_PATH:-/var/lib/hystron-node/config.json}"
echo "  gRPC port:   ${GRPC_PORT:-50051}"
echo "  xray API:    ${XRAY_API_ADDR:-127.0.0.1:10085}"

exec python /app/main.py
