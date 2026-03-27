from __future__ import annotations


def normalize_port_entries(ports, *, ignored_names=None):
    out = []
    ignored = {str(x).strip().lower() for x in list(ignored_names or []) if str(x).strip()}
    for item in ports or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        proto = str(item.get("proto") or "").strip().lower()
        if not name or not proto:
            continue
        if name.lower() in ignored:
            continue
        out.append({"name": name, "proto": proto, "port": item.get("port")})
    return out


def validate_normalized_ports(ports):
    found = {}
    for item in list(ports or []):
        name = str(item.get("name") or "").strip()
        proto = str(item.get("proto") or "").strip().lower()
        port_val = item.get("port")
        try:
            port_i = int(port_val)
        except Exception:
            return False, name, proto, port_val, None, "invalid_port", found
        if port_i <= 0 or port_i > 65535:
            return False, name, proto, port_val, port_i, "out_of_range", found
        if proto not in ("tcp", "udp"):
            return False, name, proto, port_val, port_i, "invalid_proto", found
        found[name] = (proto, port_i)
    return True, None, None, None, None, None, found


def validate_legacy_ports(game_port, rcon_port):
    try:
        gp = int(game_port)
        rp = int(rcon_port)
    except Exception:
        return False, None, None, "missing"
    if gp <= 0 or gp > 65535:
        return False, gp, None, "game_out_of_range"
    if rp <= 0 or rp > 65535:
        return False, gp, rp, "rcon_out_of_range"
    return True, gp, rp, None


def sort_ports(ports, *, preferred_order=None):
    order = {str(name): idx for idx, name in enumerate(list(preferred_order or []))}
    return sorted(
        list(ports or []),
        key=lambda item: (
            order.get(str(item.get("name") or ""), 99),
            str(item.get("name") or ""),
            str(item.get("proto") or ""),
            int(item.get("port") or 0),
        ),
    )
