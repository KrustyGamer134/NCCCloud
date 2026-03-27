from __future__ import annotations


class GenericRconClient:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        password: str,
        timeout_seconds: float = 2.0,
        socket_module,
        struct_module,
        auth_packet_type: int,
        command_packet_type: int,
    ):
        self._host = host
        self._port = int(port)
        self._password = password
        self._timeout = float(timeout_seconds)
        self._socket_module = socket_module
        self._struct_module = struct_module
        self._auth_packet_type = int(auth_packet_type)
        self._command_packet_type = int(command_packet_type)

    def wire(self, message: str) -> None:
        return None

    def command_name(self, command: str) -> str:
        return str(command or "").strip()

    def exec(self, command: str) -> str:
        command = str(command)
        self.wire(f"connect: {self._host}:{self._port} timeout={self._timeout}")

        try:
            with self._socket_module.socket(self._socket_module.AF_INET, self._socket_module.SOCK_STREAM) as sock:
                sock.settimeout(self._timeout)

                try:
                    sock.connect((self._host, self._port))
                    self.wire("connect ok")
                except Exception as exc:
                    self.wire(f"connect error: {type(exc).__name__}: {exc}")
                    raise

                auth_payload_len = len((self._password or "").encode("utf-8"))
                self.wire(f"auth send: id=1 type={self._auth_packet_type} payload_len={auth_payload_len}")
                auth_sent = self._send_packet(sock, 1, self._auth_packet_type, self._password)
                self.wire(f"auth send ok: bytes={auth_sent}")

                try:
                    auth_id, auth_type, _auth_body, auth_bytes = self._recv_packet_with_meta(sock)
                    self.wire(f"auth recv: bytes={auth_bytes} id={auth_id} type={auth_type}")
                    if auth_id == -1:
                        raise RuntimeError("RCON auth failed")
                    if auth_id != 1:
                        auth_id, auth_type, _auth_body, auth_bytes = self._recv_packet_with_meta(sock)
                        self.wire(f"auth recv: bytes={auth_bytes} id={auth_id} type={auth_type}")
                except self._socket_module.timeout:
                    self.wire("auth recv timeout")
                    raise
                except Exception as exc:
                    self.wire(f"auth recv error: {type(exc).__name__}: {exc}")
                    raise

                if auth_id == -1:
                    raise RuntimeError("RCON auth failed")

                cmd_name = self.command_name(command)
                cmd_payload_len = len(command.encode("utf-8"))
                self.wire(f"command send: {cmd_name} id=2 type={self._command_packet_type} payload_len={cmd_payload_len}")
                cmd_sent = self._send_packet(sock, 2, self._command_packet_type, command)
                self.wire(f"command send ok: bytes={cmd_sent}")

                try:
                    req_id, req_type, body, cmd_bytes = self._recv_packet_with_meta(sock)
                    self.wire(f"command recv: bytes={cmd_bytes} id={req_id} type={req_type}")
                    return body
                except self._socket_module.timeout:
                    self.wire("command recv timeout")
                    raise
                except Exception as exc:
                    self.wire(f"command recv error: {type(exc).__name__}: {exc}")
                    raise
        except Exception as exc:
            self.wire(f"error: {type(exc).__name__}: {exc}")
            raise

    def _send_packet(self, sock, req_id: int, ptype: int, body: str) -> int:
        body_bytes = (body or "").encode("utf-8") + b"\x00"
        packet = self._struct_module.pack("<ii", int(req_id), int(ptype)) + body_bytes + b"\x00"
        length = self._struct_module.pack("<i", len(packet))
        wire = length + packet
        sock.sendall(wire)
        return len(wire)

    def _recv_exact(self, sock, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise RuntimeError("RCON connection closed")
            buf += chunk
        return buf

    def _recv_packet_with_meta(self, sock):
        length_bytes = self._recv_exact(sock, 4)
        (length,) = self._struct_module.unpack("<i", length_bytes)
        payload = self._recv_exact(sock, length)
        req_id, ptype = self._struct_module.unpack("<ii", payload[:8])
        body_bytes = payload[8:]
        body = body_bytes.rstrip(b"\x00").decode("utf-8", errors="replace")
        return req_id, ptype, body, (4 + len(payload))

    def _recv_packet(self, sock):
        req_id, ptype, body, _bytes_total = self._recv_packet_with_meta(sock)
        return req_id, ptype, body
