import os
import sys
from dataclasses import dataclass

VERSION = "1.0.1"


@dataclass(frozen=True)
class Config:
    api_key: str
    grpc_port: int
    xray_bin: str
    xray_config_path: str
    xray_api_addr: str
    grpc_tls_cert: str | None
    grpc_tls_key: str | None


def load_config() -> Config:
    api_key = os.environ.get("HYSTRON_NODE_API_KEY", "")
    if not api_key:
        print("ERROR: HYSTRON_NODE_API_KEY is not set", file=sys.stderr)
        sys.exit(1)
    if len(api_key) < 32:
        print(
            f"ERROR: HYSTRON_NODE_API_KEY is too short ({len(api_key)} chars, min 32)",
            file=sys.stderr,
        )
        sys.exit(1)

    grpc_port_str = os.environ.get("GRPC_PORT", "50051")
    try:
        grpc_port = int(grpc_port_str)
    except ValueError:
        print(f"ERROR: GRPC_PORT must be an integer, got '{grpc_port_str}'", file=sys.stderr)
        sys.exit(1)

    tls_cert = os.environ.get("GRPC_TLS_CERT") or None
    tls_key = os.environ.get("GRPC_TLS_KEY") or None
    if (tls_cert is None) != (tls_key is None):
        print(
            "ERROR: GRPC_TLS_CERT and GRPC_TLS_KEY must both be set or both be unset",
            file=sys.stderr,
        )
        sys.exit(1)

    return Config(
        api_key=api_key,
        grpc_port=grpc_port,
        xray_bin=os.environ.get("XRAY_BIN", "/usr/local/bin/xray"),
        xray_config_path=os.environ.get("XRAY_CONFIG_PATH", "/var/lib/hystron-node/config.json"),
        xray_api_addr=os.environ.get("XRAY_API_ADDR", "127.0.0.1:10085"),
        grpc_tls_cert=tls_cert,
        grpc_tls_key=tls_key,
    )
