# ─── Stage 1: Builder ────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install dependencies into an isolated venv
COPY pyproject.toml .
RUN uv sync --no-dev

# Copy sources
COPY proto/ proto/
COPY scripts/ scripts/
COPY app/ app/
COPY main.py .

# Generate protobuf stubs
RUN uv run python scripts/gen_proto.py

# Download xray-core from GitHub releases
RUN apt-get update -qq && apt-get install -y -qq unzip wget && \
    ARCH=$(uname -m) && \
    case "$ARCH" in \
        x86_64)  XRAY_ARCH="64" ;; \
        aarch64) XRAY_ARCH="arm64-v8a" ;; \
        armv7l)  XRAY_ARCH="arm32-v7a" ;; \
        *)       XRAY_ARCH="64" ;; \
    esac && \
    wget -q "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-${XRAY_ARCH}.zip" -O /tmp/xray.zip && \
    unzip /tmp/xray.zip xray geoip.dat geosite.dat -d /usr/local/share/xray && \
    chmod +x /usr/local/share/xray/xray && \
    ln -s /usr/local/share/xray/xray /usr/local/bin/xray && \
    rm -f /tmp/xray.zip

# ─── Stage 2: Runtime ────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

# Copy venv from builder
COPY --from=builder /build/.venv /app/.venv

# Copy xray binary and geo data files
COPY --from=builder /usr/local/share/xray /usr/local/share/xray
RUN ln -s /usr/local/share/xray/xray /usr/local/bin/xray

# Copy application code (includes generated stubs from builder)
COPY --from=builder /build/app /app/app
COPY --from=builder /build/main.py /app/main.py
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Data directory — user mounts their xray config.json here
RUN mkdir -p /var/lib/hystron-node

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 50051

ENTRYPOINT ["/app/start.sh"]
