#!/usr/bin/env bash
# Hystron Node installation script
# Usage: sudo bash install.sh [install|uninstall|update]
set -euo pipefail

REPO_URL="https://github.com/BX-Team/hystron-node"
IMAGE_NAME="ghcr.io/bx-team/hystron-node"
INSTALL_DIR="/opt/hystron-node"
DATA_DIR="/var/lib/hystron-node"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[hystron-node]${NC} $*"; }
warn()  { echo -e "${YELLOW}[hystron-node]${NC} $*"; }
error() { echo -e "${RED}[hystron-node]${NC} $*" >&2; exit 1; }

# ── root check ────────────────────────────────────────────────────────────────
require_root() {
    if [[ $EUID -ne 0 ]]; then
        error "This script must be run as root (sudo $0)."
    fi
}

# ── docker compose command detection ─────────────────────────────────────────
detect_compose() {
    if command -v docker &>/dev/null && docker compose version &>/dev/null 2>&1; then
        COMPOSE_CMD="docker compose"
    elif command -v docker-compose &>/dev/null; then
        COMPOSE_CMD="docker-compose"
    else
        COMPOSE_CMD=""
    fi
}

# ── docker install ────────────────────────────────────────────────────────────
install_docker() {
    if command -v docker &>/dev/null; then
        info "Docker already installed: $(docker --version)"
        return
    fi
    info "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
    info "Docker installed: $(docker --version)"
}

# ── version selection ─────────────────────────────────────────────────────────
choose_version() {
    echo ""
    echo "Select the Hystron Node version to install:"
    echo "  1) latest  (default)"
    echo "  2) Specific version (e.g. 1.2.3)"
    echo ""
    read -rp "Enter choice [1-2] (default: 1): " ver_choice
    ver_choice="${ver_choice:-1}"

    case "$ver_choice" in
        1) NODE_VERSION="latest" ;;
        2)
            read -rp "Enter version (e.g. 1.2.3): " custom_ver
            NODE_VERSION="${custom_ver:-latest}"
            ;;
        *) warn "Invalid choice, using latest."; NODE_VERSION="latest" ;;
    esac
    info "Using image: ${IMAGE_NAME}:${NODE_VERSION}"
}

# ── port selection ────────────────────────────────────────────────────────────
choose_ports() {
    echo ""
    read -rp "gRPC port [50051]: " GRPC_PORT
    GRPC_PORT="${GRPC_PORT:-50051}"
}

# ── .env generation ───────────────────────────────────────────────────────────
setup_env() {
    local env_file="${INSTALL_DIR}/.env"
    if [[ -f "$env_file" ]]; then
        warn ".env already exists — skipping generation. Edit ${env_file} if needed."
        return
    fi

    info "Generating API key and .env..."
    local api_key
    api_key=$(python3 -c "import secrets; print(secrets.token_hex(32))")

    cat > "$env_file" <<EOF
HYSTRON_NODE_VERSION=${NODE_VERSION:-latest}

HYSTRON_NODE_API_KEY=${api_key}
GRPC_PORT=${GRPC_PORT:-50051}

XRAY_CONFIG_PATH=/var/lib/hystron-node/config.json
XRAY_API_ADDR=127.0.0.1:10085
# Uncomment to enable TLS:
# GRPC_TLS_CERT=/var/lib/hystron-node/tls/server.crt
# GRPC_TLS_KEY=/var/lib/hystron-node/tls/server.key
EOF
    chmod 600 "$env_file"
    info ".env created at ${env_file}"
    echo ""
    warn "┌─────────────────────────────────────────────────────────────┐"
    warn "│  Save this API key — you will need it to register the node  │"
    warn "│  in your Hystron panel.                                      │"
    warn "│                                                              │"
    warn "│  API key: ${api_key}  │"
    warn "└─────────────────────────────────────────────────────────────┘"
    echo ""
}

# ── fetch compose file ────────────────────────────────────────────────────────
fetch_compose() {
    mkdir -p "$INSTALL_DIR"
    info "Downloading docker-compose.yml to ${INSTALL_DIR}..."
    curl -fsSL "${REPO_URL}/raw/refs/heads/master/docker-compose.yml" \
        -o "${INSTALL_DIR}/docker-compose.yml"
    info "docker-compose.yml downloaded."
}

# ── install ───────────────────────────────────────────────────────────────────
do_install() {
    require_root
    install_docker
    detect_compose
    if [[ -z "$COMPOSE_CMD" ]]; then
        error "Docker Compose not found. Please install Docker with Compose support."
    fi

    fetch_compose
    choose_version
    choose_ports
    setup_env

    info "Preparing data directory ${DATA_DIR}..."
    mkdir -p "$DATA_DIR"

    if [[ ! -f "${DATA_DIR}/config.json" ]]; then
        warn "No config.json found at ${DATA_DIR}/config.json"
        warn "Place your xray config.json there before starting the node."
        warn "See README for the required sections (api, stats, policy)."
    fi

    info "Pulling image ${IMAGE_NAME}:${NODE_VERSION}..."
    docker pull "${IMAGE_NAME}:${NODE_VERSION}"

    info "Starting Hystron Node..."
    $COMPOSE_CMD -f "${INSTALL_DIR}/docker-compose.yml" --env-file "${INSTALL_DIR}/.env" up -d

    echo "${NODE_VERSION}" > "${INSTALL_DIR}/.node_version"

    local server_ip
    server_ip=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}') \
        || server_ip=$(hostname -I 2>/dev/null | awk '{print $1}') \
        || server_ip="<server-ip>"

    echo ""
    info "=== Installation complete ==="
    info "  gRPC endpoint → ${server_ip}:${GRPC_PORT:-50051}"
    info "  Data dir      → ${DATA_DIR}"
    info "  Logs          → docker logs -f hystron-node"
    echo ""
    info "  Register this node in the Hystron panel:"
    info "    grpc_addr: ${server_ip}:${GRPC_PORT:-50051}"
    info "    api_key:   see ${INSTALL_DIR}/.env"
}

# ── uninstall ─────────────────────────────────────────────────────────────────
do_uninstall() {
    require_root
    detect_compose
    warn "Stopping and removing Hystron Node..."
    if [[ -n "$COMPOSE_CMD" && -f "${INSTALL_DIR}/docker-compose.yml" ]]; then
        $COMPOSE_CMD -f "${INSTALL_DIR}/docker-compose.yml" down -v 2>/dev/null || true
    else
        docker stop hystron-node 2>/dev/null || true
        docker rm   hystron-node 2>/dev/null || true
    fi
    rm -rf "$INSTALL_DIR"
    info "Hystron Node uninstalled. Data in ${DATA_DIR} was preserved."
}

# ── update ────────────────────────────────────────────────────────────────────
do_update() {
    require_root
    detect_compose
    if [[ -z "$COMPOSE_CMD" ]]; then
        error "Docker Compose not found."
    fi
    if [[ ! -d "$INSTALL_DIR" ]]; then
        error "Hystron Node is not installed at ${INSTALL_DIR}."
    fi

    fetch_compose

    local saved_version="latest"
    [[ -f "${INSTALL_DIR}/.node_version" ]] && saved_version=$(cat "${INSTALL_DIR}/.node_version")

    info "Pulling image ${IMAGE_NAME}:${saved_version}..."
    docker pull "${IMAGE_NAME}:${saved_version}"

    $COMPOSE_CMD -f "${INSTALL_DIR}/docker-compose.yml" --env-file "${INSTALL_DIR}/.env" up -d

    info "Hystron Node updated to ${saved_version}."
}

# ── entrypoint ────────────────────────────────────────────────────────────────
usage() {
    echo "Usage: $0 {install|uninstall|update}"
    exit 1
}

case "${1:-install}" in
    install)   do_install ;;
    uninstall) do_uninstall ;;
    update)    do_update ;;
    *)         usage ;;
esac
