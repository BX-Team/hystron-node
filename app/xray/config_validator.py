import json
import logging

logger = logging.getLogger(__name__)


def load_tag_protocol_map(config_path: str) -> dict[str, int]:
    """Build a {inbound_tag: Protocol enum int} mapping from xray config.json."""
    from app.gen import hystron_node_pb2

    _PROTO_MAP = {
        "vless": hystron_node_pb2.VLESS,
        "trojan": hystron_node_pb2.TROJAN,
    }
    try:
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    result: dict[str, int] = {}
    for inbound in cfg.get("inbounds", []):
        tag = inbound.get("tag")
        proto = inbound.get("protocol", "").lower()
        if tag and proto in _PROTO_MAP:
            result[tag] = _PROTO_MAP[proto]
    return result


class ConfigValidationError(Exception):
    pass


def validate_xray_config(config_path: str, xray_api_addr: str) -> None:
    """
    Validate that the user's xray config.json has all required sections
    for hystron-node to function correctly.

    Raises ConfigValidationError with a descriptive message on failure.
    """
    try:
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        raise ConfigValidationError(
            f"Config file not found: {config_path}\nPlace your xray config.json at /var/lib/hystron-node/config.json"
        )
    except json.JSONDecodeError as exc:
        raise ConfigValidationError(f"Config file is not valid JSON: {exc}")

    errors: list[str] = []

    # 1. api block with required services
    api = cfg.get("api", {})
    if not api:
        errors.append(
            'Missing \'api\' block. Add: {"api": {"tag": "api", "services": ["HandlerService", "StatsService"]}}'
        )
    else:
        services = api.get("services", [])
        for svc in ("HandlerService", "StatsService"):
            if svc not in services:
                errors.append(f"'api.services' must include '{svc}'")

    # 2. stats block
    if "stats" not in cfg:
        errors.append("Missing 'stats' block. Add: {\"stats\": {}}")

    # 3. policy with per-user stats enabled
    policy = cfg.get("policy", {})
    levels = policy.get("levels", {})
    level0 = levels.get("0", {})
    if not level0.get("statsUserUplink") or not level0.get("statsUserDownlink"):
        errors.append("policy.levels.0 must have statsUserUplink: true and statsUserDownlink: true")

    # 4. dokodemo-door inbound for xray API at the configured address
    host, port_str = _split_addr(xray_api_addr)
    try:
        api_port = int(port_str)
    except ValueError:
        api_port = 10085

    inbounds = cfg.get("inbounds", [])
    api_inbound = next(
        (ib for ib in inbounds if ib.get("protocol") == "dokodemo-door" and ib.get("port") == api_port),
        None,
    )
    if api_inbound is None:
        errors.append(
            f"Missing dokodemo-door inbound on port {api_port} for the xray API.\n"
            f'  Add to inbounds: {{"tag": "api", "listen": "{host}", '
            f'"port": {api_port}, "protocol": "dokodemo-door", '
            f'"settings": {{"address": "{host}"}}}}'
        )

    # 5. routing rule for the api inbound
    routing = cfg.get("routing", {})
    rules = routing.get("rules", [])
    api_tag = api.get("tag", "api") if api else "api"
    has_api_route = any(api_tag in rule.get("inboundTag", []) or rule.get("outboundTag") == api_tag for rule in rules)
    if not has_api_route:
        errors.append(
            f"Missing routing rule for api tag '{api_tag}'.\n"
            f'  Add to routing.rules: {{"type": "field", '
            f'"inboundTag": ["{api_tag}"], "outboundTag": "{api_tag}"}}'
        )

    if errors:
        msg = "xray config.json validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ConfigValidationError(msg)

    logger.info("xray config validation passed.")


def _split_addr(addr: str) -> tuple[str, str]:
    if ":" in addr:
        host, port = addr.rsplit(":", 1)
        return host, port
    return addr, "10085"
