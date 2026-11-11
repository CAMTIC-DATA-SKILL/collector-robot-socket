"""TCP 소켓에서 프레임 하나를 읽고, 필요하면 그 전에 요청 한 줄을 보낸다."""
import logging
import socket

from model.socket_map_model import Framing, SocketMapSettings

from .config import SocketClientConfig
from .exceptions import SocketClientError, SocketErrorCode

logger = logging.getLogger(__name__)

_RECV = 4096


class SocketClient:
    """수집 스레드 한 곳에서만 쓴다. 프레임 경계를 넘는 바이트는 다음 읽기까지 들고 있는다."""

    def __init__(self, config: SocketClientConfig) -> None:
        if not config.host.strip():
            raise ValueError("SOCKET_HOST 가 비어 있다")
        self.config = config
        self._sock: socket.socket | None = None
        self._pending = b""

    def connect(self) -> None:
        if self._sock is not None:
            return
        try:
            sock = socket.create_connection((self.config.host, self.config.port), self.config.timeout)
            sock.settimeout(self.config.timeout)
        except TimeoutError as e:
            raise SocketClientError(SocketErrorCode.TIMEOUT, str(e)) from e
        except OSError as e:
            raise SocketClientError(SocketErrorCode.CONNECT_FAILED, str(e)) from e
        self._sock = sock
        self._pending = b""
        logger.info("TCP %s:%s timeout=%.1fs", self.config.host, self.config.port, self.config.timeout)

    def close(self) -> None:
        sock, self._sock = self._sock, None
        self._pending = b""
        if sock is not None:
            try:
                sock.close()
            except OSError as e:
                logger.debug("socket close failed: %s", e)

    def read_frame(self, settings: SocketMapSettings) -> str:
        """request 가 있으면 먼저 보내고, framing 규칙으로 프레임 하나를 문자열로 돌려준다."""
        if settings.request is not None:
            self._send(settings.request, settings)
        raw = self._read_raw(settings)
        try:
            return raw.decode(settings.encoding)
        except UnicodeError as e:
            raise SocketClientError(SocketErrorCode.PROTOCOL_ERROR, f"디코딩 실패: {e}") from e

    def _send(self, text: str, settings: SocketMapSettings) -> None:
        payload = text.encode(settings.encoding)
        if settings.framing is not Framing.FIXED:
            ending = _send_ending(settings.framing)
            if not payload.endswith(ending):
                payload += ending
        self._write(payload)

    def _write(self, payload: bytes) -> None:
        if self._sock is None:
            raise SocketClientError(SocketErrorCode.CONNECT_FAILED, "소켓이 없다")
        try:
            self._sock.sendall(payload)
        except TimeoutError as e:
            raise SocketClientError(SocketErrorCode.TIMEOUT, str(e)) from e
        except OSError as e:
            raise SocketClientError(SocketErrorCode.CONNECTION_CLOSED, str(e)) from e

    def _read_raw(self, settings: SocketMapSettings) -> bytes:
        if settings.framing is Framing.FIXED:
            while len(self._pending) < settings.max_bytes:
                self._fill()
            raw, self._pending = self._pending[: settings.max_bytes], self._pending[settings.max_bytes :]
            return raw
        while True:
            cut = _cut(self._pending, settings.framing)
            if cut is not None:
                raw, self._pending = cut
                return raw
            if len(self._pending) >= settings.max_bytes:
                raise SocketClientError(
                    SocketErrorCode.PROTOCOL_ERROR, f"구분자 없이 {settings.max_bytes}바이트를 넘었다"
                )
            self._fill()

    def _fill(self) -> None:
        if self._sock is None:
            raise SocketClientError(SocketErrorCode.CONNECT_FAILED, "소켓이 없다")
        try:
            chunk = self._sock.recv(_RECV)
        except TimeoutError as e:
            raise SocketClientError(SocketErrorCode.TIMEOUT, str(e)) from e
        except OSError as e:
            raise SocketClientError(SocketErrorCode.CONNECTION_CLOSED, str(e)) from e
        if not chunk:
            raise SocketClientError(SocketErrorCode.CONNECTION_CLOSED, "상대가 연결을 닫았다")
        self._pending += chunk


def _send_ending(framing: Framing) -> bytes:
    if framing is Framing.CR:
        return b"\r"
    if framing is Framing.LF:
        return b"\n"
    return b"\r\n"


def _cut(buf: bytes, framing: Framing) -> tuple[bytes, bytes] | None:
    tokens = (b"\n",) if framing is Framing.LF else (b"\r",) if framing is Framing.CR else (b"\r\n", b"\n", b"\r")
    found: list[tuple[int, bytes]] = []
    for token in tokens:
        index = buf.find(token)
        if index >= 0:
            found.append((index, token))
    if not found:
        return None
    index, token = min(found, key=lambda item: (item[0], -len(item[1])))
    return buf[:index], buf[index + len(token) :]
