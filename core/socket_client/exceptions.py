"""TCP 소켓 클라이언트 예외. 코드 체계는 collector-robot-modbus 와 같다.

  1xxx  연결 - 재연결 대상
  2xxx  칸 없음 (E-2203)
  3xxx  프레임이 상한을 넘거나 글자 디코딩에 실패 - 스트림 위치가 어긋나므로 재연결
"""
from enum import Enum


class SocketErrorCode(str, Enum):
    CONNECT_FAILED = "E-1001"
    CONNECTION_CLOSED = "E-1002"
    TIMEOUT = "E-1003"

    FIELD_MISSING = "E-2203"

    PROTOCOL_ERROR = "E-3001"

    UNKNOWN = "E-9001"

    @property
    def requires_reconnect(self) -> bool:
        return self in (
            SocketErrorCode.CONNECT_FAILED,
            SocketErrorCode.CONNECTION_CLOSED,
            SocketErrorCode.TIMEOUT,
            SocketErrorCode.PROTOCOL_ERROR,
        )


class SocketClientError(Exception):
    def __init__(self, code: SocketErrorCode, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code.value}({code.name}) {detail}".rstrip())
