############################################################
# SECTION: Core Port Availability Check
# Purpose:
#     Deterministic, universal port availability check.
#
# Phase:
#     CG-PLUGIN-CONFIG-1
#
# Constraints:
#     - Bind attempts only (localhost)
#     - Deterministic output shape
############################################################

from __future__ import annotations

from typing import Any, Dict, List
import socket


def check_ports_availability(port_specs: List[Dict[str, Any]]) -> Dict[str, Any]:
    blocked: List[Dict[str, Any]] = []

    for spec in port_specs or []:
        name = spec.get("name")
        port = spec.get("port")
        proto = spec.get("proto")

        # Validate port
        try:
            port_int = int(port or 0)
        except Exception:
            blocked.append({
                "name": name,
                "port": port,
                "proto": proto,
                "reason": "invalid_port",
            })
            continue

        # Validate proto
        proto_norm = str(proto).lower() if proto is not None else ""
        if proto_norm not in ("tcp", "udp"):
            blocked.append({
                "name": name,
                "port": port_int,
                "proto": proto,
                "reason": "invalid_proto",
            })
            continue

        sock_type = socket.SOCK_STREAM if proto_norm == "tcp" else socket.SOCK_DGRAM

        s = socket.socket(socket.AF_INET, sock_type)
        try:
            # Must bind to localhost only (deterministic + safe)
            s.bind(("127.0.0.1", port_int))
        except OSError as e:
            blocked.append({
                "name": name,
                "port": port_int,
                "proto": proto_norm,
                "reason": str(e),
            })
        finally:
            try:
                s.close()
            except Exception:
                pass

    return {
        "ok": len(blocked) == 0,
        "blocked": blocked,
    }
