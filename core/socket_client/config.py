from dataclasses import dataclass


@dataclass(slots=True)
class SocketClientConfig:
    """TCP 접속. 환경 변수 값은 루트 config.py 에서 채운다."""

    host: str = "127.0.0.1"
    port: int = 5002
    timeout: float = 30.0
