"""TCP 프레임 읽기 스모크. 장비 없이 로컬 소켓으로 돈다.

    python script/smoke_socket.py
"""
import socket
import threading

from pydantic import ValidationError

from _smoke import ROOT, SmokeAbort, SmokeRunner, expect
from core.socket_client import SocketClient, SocketClientConfig, SocketErrorCode, SocketMap
from model.protocol_model import MsgDataDTO, MsgSampleDTO
from model.sample_model import Sample
from model.socket_map_model import PointType, SocketMapSettings

LINE = b"10,1.5,home\r\n9,2.0,away\n"


def main() -> int:
    runner = SmokeRunner("collector-robot-soket")
    try:
        runner.check("scara map loads", _load_map, required=True)
        runner.check("addr defaults to the point name", _addr_key, required=True)
        runner.check("empty points become the whole line", _empty_points)
        server, port = _serve(LINE)
        try:
            runner.check("crlf frames and fields", lambda: _read(port), required=True)
            runner.check("missing column is a point error", lambda: _missing(port))
        finally:
            server.close()
        runner.check("overlong frame reconnects", _overlong)
        runner.check("peer close reconnects", _closed)
        runner.check("request is sent before read", _request)
    except SmokeAbort:
        pass
    return runner.finish()


def _load_map() -> str:
    socket_map = SocketMap.from_json(ROOT / "socket_map.json")
    expect(socket_map.settings.framing.value, "crlf")
    expect(socket_map.settings.max_bytes, 500)
    expect(len(socket_map.settings.points), 22)
    expect([p.addr for p in socket_map.settings.points], [p.name for p in socket_map.settings.points])
    return socket_map.describe_plan().split(":", 1)[0]


def _addr_key() -> str:
    settings = SocketMapSettings.model_validate(
        {"points": [{"name": "seq", "index": 2, "type": "f64"}, {"name": "speed", "addr": "tcp_speed", "index": 1}]}
    )
    expect(settings.points[0].addr, "seq")
    expect(settings.points[1].addr, "tcp_speed")
    try:
        SocketMapSettings.model_validate(
            {"points": [{"name": "a", "addr": "same"}, {"name": "b", "addr": "same"}]}
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("중복 addr 이 통과했다")
    sample = Sample(addr="tcp_speed", name="speed", index=1, type=PointType.F64, value=1.5, error=None)
    body = MsgDataDTO(
        device_key="scara-1",
        sample_ms=1,
        samples=[MsgSampleDTO.model_validate(sample.model_dump())],
    )
    wire = body.model_dump(mode="json")["samples"][0]
    expect(wire["addr"], "tcp_speed")
    expect(wire["name"], "speed")
    return wire["addr"]


def _empty_points() -> str:
    settings = SocketMapSettings.model_validate({"points": []})
    point = settings.points[0]
    expect(point.name, "line")
    expect(point.addr, "line")
    expect(point.index, None)
    return point.type.value


def _serve(payload: bytes, *, hold: bool = True) -> tuple[socket.socket, int]:
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def run() -> None:
        conn, _ = server.accept()
        if payload:
            conn.sendall(payload)
        if not hold:
            conn.close()

    threading.Thread(target=run, daemon=True).start()
    return server, port


def _client(port: int) -> SocketClient:
    client = SocketClient(SocketClientConfig(host="127.0.0.1", port=port, timeout=2.0))
    client.connect()
    return client


def _map() -> SocketMapSettings:
    return SocketMapSettings.model_validate(
        {
            "framing": "crlf",
            "max_bytes": 64,
            "points": [
                {"name": "line", "type": "str"},
                {"name": "seq", "addr": "cycle", "index": 0, "type": "i64"},
                {"name": "speed", "index": 1, "type": "f64", "scale": 0.1},
                {"name": "waypoint", "index": 2, "type": "str"},
            ],
        }
    )


def _read(port: int) -> str:
    client = _client(port)
    try:
        first = {s.name: s for s in SocketMap(_map()).read(client)}
        second = {s.name: s for s in SocketMap(_map()).read(client)}
    finally:
        client.close()
    expect(first["line"].value, "10,1.5,home")
    expect(first["line"].addr, "line")
    expect(first["seq"].value, 10)
    expect(first["seq"].addr, "cycle")
    expect(round(first["speed"].value, 10), 0.15)
    expect(first["waypoint"].value, "home")
    expect(second["seq"].value, 9)
    expect(second["waypoint"].value, "away")
    return "two frames"


def _missing(port: int) -> str:
    settings = SocketMapSettings.model_validate(
        {"max_bytes": 32, "points": [{"name": "only", "index": 5, "type": "str"}]}
    )
    server, listen = _serve(b"a,b\r\n")
    try:
        client = _client(listen)
        try:
            sample = SocketMap(settings).read(client)[0]
        finally:
            client.close()
    finally:
        server.close()
    expect(sample.error, SocketErrorCode.FIELD_MISSING.value)
    expect(sample.value, None)
    expect(sample.addr, "only")
    return sample.error or ""


def _overlong() -> str:
    settings = SocketMapSettings.model_validate({"max_bytes": 8, "points": [{"name": "line", "type": "str"}]})
    server, port = _serve(b"0123456789ABCDEF")
    try:
        client = _client(port)
        try:
            try:
                SocketMap(settings).read(client)
            except Exception as e:
                from core.socket_client import SocketClientError

                if not isinstance(e, SocketClientError) or not e.code.requires_reconnect:
                    raise
                return e.code.value
            raise AssertionError("상한 초과가 샘플 오류로 남았다")
        finally:
            client.close()
    finally:
        server.close()


def _closed() -> str:
    settings = SocketMapSettings.model_validate({"points": [{"name": "line", "type": "str"}]})
    server, port = _serve(b"", hold=False)
    try:
        client = _client(port)
        try:
            try:
                SocketMap(settings).read(client)
            except Exception as e:
                from core.socket_client import SocketClientError

                if not isinstance(e, SocketClientError) or e.code is not SocketErrorCode.CONNECTION_CLOSED:
                    raise
                return e.code.value
            raise AssertionError("연결 종료가 샘플로 남았다")
        finally:
            client.close()
    finally:
        server.close()


def _request() -> str:
    settings = SocketMapSettings.model_validate(
        {"request": "PING", "max_bytes": 32, "points": [{"name": "line", "type": "str"}]}
    )
    box: dict[str, bytes] = {}
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def run() -> None:
        conn, _ = server.accept()
        data = b""
        while b"\n" not in data:
            data += conn.recv(64)
        box["req"] = data
        conn.sendall(b"pong\r\n")
        conn.close()

    threading.Thread(target=run, daemon=True).start()
    client = _client(port)
    try:
        sample = SocketMap(settings).read(client)[0]
    finally:
        client.close()
        server.close()
    expect(box["req"], b"PING\r\n")
    expect(sample.value, "pong")
    return "PING"


if __name__ == "__main__":
    raise SystemExit(main())
