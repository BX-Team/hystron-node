"""
Generate gRPC Python stubs from .proto files.

Usage:
    uv run python scripts/gen_proto.py
    # or
    python scripts/gen_proto.py

Output: app/gen/
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
PROTO_DIR = ROOT / "proto"
OUT_DIR = ROOT / "app" / "gen"

# All proto files to compile, in dependency order
PROTO_FILES = [
    # xray internals
    "xray/common/serial/typed_message.proto",
    "xray/common/protocol/user.proto",
    "xray/core/config.proto",
    "xray/app/stats/command/command.proto",
    "xray/app/proxyman/command/command.proto",
    "xray/proxy/vless/account/config.proto",
    "xray/proxy/trojan/config.proto",
    # hystron-node service
    "hystron_node.proto",
]

# Map proto package → generated module name (for clean imports in app/)
OUTPUT_MODULE_NAMES = {
    "xray/common/serial/typed_message.proto": "xray_typed_message",
    "xray/common/protocol/user.proto": "xray_user",
    "xray/core/config.proto": "xray_core_config",
    "xray/app/stats/command/command.proto": "xray_stats",
    "xray/app/proxyman/command/command.proto": "xray_handler",
    "xray/proxy/vless/account/config.proto": "xray_vless_account",
    "xray/proxy/trojan/config.proto": "xray_trojan_account",
    "hystron_node.proto": "hystron_node",
}


def main() -> None:
    try:
        from grpc_tools import protoc
    except ImportError:
        print("ERROR: grpcio-tools is not installed. Run: uv sync", file=sys.stderr)
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "__init__.py").write_text("")

    # We use a temp output dir, then rename files to clean names
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        for proto_rel in PROTO_FILES:
            proto_abs = str(PROTO_DIR / proto_rel)
            args = [
                "grpc_tools.protoc",
                f"--proto_path={PROTO_DIR}",
                f"--python_out={tmp}",
                f"--grpc_python_out={tmp}",
                proto_abs,
            ]
            ret = protoc.main(args)
            if ret != 0:
                print(f"ERROR: Failed to compile {proto_rel}", file=sys.stderr)
                sys.exit(1)
            print(f"  compiled: {proto_rel}")

        # Rename generated files and fix imports
        for proto_rel, mod_name in OUTPUT_MODULE_NAMES.items():
            # Determine where protoc put the generated file
            # protoc mirrors the directory structure of --proto_path
            stem = Path(proto_rel).stem  # e.g. "command", "config", "hystron_node"
            subdir = Path(proto_rel).parent  # e.g. "xray/app/stats/command"

            pb2_src = tmp_path / subdir / f"{stem}_pb2.py"
            grpc_src = tmp_path / subdir / f"{stem}_pb2_grpc.py"

            pb2_dst = OUT_DIR / f"{mod_name}_pb2.py"
            grpc_dst = OUT_DIR / f"{mod_name}_pb2_grpc.py"

            if pb2_src.exists():
                content = pb2_src.read_text()
                content = _fix_imports(content, OUTPUT_MODULE_NAMES)
                pb2_dst.write_text(content)
            if grpc_src.exists():
                content = grpc_src.read_text()
                content = _fix_imports(content, OUTPUT_MODULE_NAMES)
                grpc_dst.write_text(content)

    print(f"\nStubs written to: {OUT_DIR}")


def _fix_imports(content: str, name_map: dict[str, str]) -> str:
    """Replace generated module import paths with our flat app.gen.* names."""
    import re

    # protoc generates imports like:
    #   from xray.common.serial import typed_message_pb2 as ...
    # We need to map these to:
    #   from app.gen import xray_typed_message_pb2 as ...

    for proto_rel, mod_name in name_map.items():
        stem = Path(proto_rel).stem
        package_path = str(Path(proto_rel).parent).replace(os.sep, ".").replace("/", ".")
        if package_path == ".":
            old_import = f"import {stem}_pb2"
            new_import = f"from app.gen import {mod_name}_pb2"
        else:
            old_import = f"from {package_path} import {stem}_pb2"
            new_import = f"from app.gen import {mod_name}_pb2"
        content = content.replace(old_import, new_import)

    return content


if __name__ == "__main__":
    main()
