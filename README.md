# Hystron Node: Xray-core Node Agent for Hystron

Hystron Node is a lightweight daemon that runs alongside **xray-core** on a proxy server and connects it to the [Hystron](https://github.com/BX-Team/hystron) management panel. It exposes a gRPC server that the panel uses to collect traffic statistics and manage users — no panel restarts or manual SSH required.

Supported protocols: **VLESS** and **Trojan**.

## How It Works

The node starts xray-core using the config you place in `/var/lib/hystron-node/config.json`, then supervises it automatically restarting on crashes. At the same time it exposes a gRPC server on port `50051` that the Hystron panel connects to with an API key.

The panel polls the node periodically to collect per-user traffic stats, and calls `AddUser`/`RemoveUser` whenever users are created or deleted — xray picks up the changes instantly without reloading its config.

## Requirements

- Linux x86_64 or ARM64
- Docker with Compose support
- A valid xray-core `config.json` with API and stats sections enabled (see [Configuration](#configuration))
- Hystron panel v1.2.0+ with xray-node support

## Installation

### Automated Installer (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/BX-Team/hystron-node/master/install.sh -o /tmp/node.sh \
  && sudo bash /tmp/node.sh install
```

The script installs Docker (if needed), pulls the image, generates an API key, and starts the container. The API key is printed at the end — save it for the panel registration step.

```bash
# Update to the latest version
curl -fsSL https://raw.githubusercontent.com/BX-Team/hystron-node/master/install.sh -o /tmp/node.sh \
  && sudo bash /tmp/node.sh update

# Uninstall (data in /var/lib/hystron-node is preserved)
curl -fsSL https://raw.githubusercontent.com/BX-Team/hystron-node/master/install.sh -o /tmp/node.sh \
  && sudo bash /tmp/node.sh uninstall
```

View logs:

```bash
docker logs -f hystron-node
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `HYSTRON_NODE_API_KEY` | **required** | API key for gRPC authentication (min 32 chars) |
| `GRPC_PORT` | `50051` | Port the node's gRPC server listens on |
| `XRAY_BIN` | `/usr/local/bin/xray` | Path to xray binary |
| `XRAY_CONFIG_PATH` | `/var/lib/hystron-node/config.json` | Path to xray config |
| `XRAY_API_ADDR` | `127.0.0.1:10085` | Address of xray's internal gRPC API |
| `GRPC_TLS_CERT` | — | Path to TLS certificate (optional) |
| `GRPC_TLS_KEY` | — | Path to TLS private key (optional) |

TLS is optional — plaintext is acceptable behind a private network or WireGuard tunnel. If `GRPC_TLS_CERT` is set, `GRPC_TLS_KEY` must also be set.

### xray config.json Requirements

Your xray config **must** include the following sections for the node to function:

```json
{
  "api": {
    "tag": "api",
    "services": ["HandlerService", "StatsService"]
  },
  "stats": {},
  "policy": {
    "levels": {
      "0": { "statsUserUplink": true, "statsUserDownlink": true }
    }
  },
  "inbounds": [
    {
      "tag": "api",
      "listen": "127.0.0.1",
      "port": 10085,
      "protocol": "dokodemo-door",
      "settings": { "address": "127.0.0.1" }
    }
  ],
  "routing": {
    "rules": [
      { "type": "field", "inboundTag": ["api"], "outboundTag": "api" }
    ]
  }
}
```

The node validates this on startup and will print a clear error message if anything is missing.

Users are identified in xray by their **email** field (set to the Hystron username). The panel will add/remove them dynamically via gRPC — no `clients` array needs to be pre-populated in the config.

## License

Released under the [MIT License](https://github.com/BX-Team/hystron-node/blob/master/LICENSE).
