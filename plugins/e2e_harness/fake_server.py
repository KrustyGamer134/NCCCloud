"""Deterministic fake server for end-to-end harness testing.

Implements the minimal Source-style RCON packet flow used by GenericRconClient.

Constraints:
  - No threads
  - No sleeps
  - Deterministic behavior
"""

from __future__ import annotations

import argparse
import socket
import struct
import sys


def _recv_exact(conn: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            raise RuntimeError("Connection closed")
        data += chunk
    return data


def _recv_packet(conn: socket.socket) -> tuple[int, int, str]:
    (length,) = struct.unpack("<i", _recv_exact(conn, 4))
    payload = _recv_exact(conn, length)
    req_id, ptype = struct.unpack("<ii", payload[:8])
    body = payload[8:].rstrip(b"\x00").decode("utf-8", errors="replace")
    return req_id, ptype, body


def _send_packet(conn: socket.socket, req_id: int, ptype: int, body: str) -> None:
    body_bytes = body.encode("utf-8") + b"\x00\x00"
    payload = struct.pack("<ii", int(req_id), int(ptype)) + body_bytes
    conn.sendall(struct.pack("<i", len(payload)) + payload)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]

    p = argparse.ArgumentParser()
    p.add_argument("--rcon-port", type=int, required=True)
    p.add_argument("--password", required=True)
    args = p.parse_args(argv)

    host = "127.0.0.1"
    port = int(args.rcon_port)
    password = str(args.password)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        s.listen(1)
        sys.stdout.write("READY\n")
        sys.stdout.flush()

        while True:
            conn, _addr = s.accept()
            with conn:
                req_id, ptype, auth_body = _recv_packet(conn)
                if ptype != 3:
                    _send_packet(conn, -1, 2, "")
                    continue
                if auth_body != password:
                    _send_packet(conn, -1, 2, "")
                    continue
                _send_packet(conn, req_id, 2, "")

                while True:
                    try:
                        command_id, command_type, command_body = _recv_packet(conn)
                    except Exception:
                        break
                    if command_type != 2:
                        _send_packet(conn, command_id, 0, "ERR")
                        continue
                    normalized = command_body.strip().strip('"')
                    _send_packet(conn, command_id, 0, "OK")
                    if normalized == "DoExit":
                        return 0


if __name__ == "__main__":
    raise SystemExit(main())
