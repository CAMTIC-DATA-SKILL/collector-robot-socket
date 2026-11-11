"""소켓 프레임 맵 JSON 스키마.

한 주기마다 프레임을 하나 읽는다.
framing:
  crlf  CR, LF, CRLF 중 먼저 오는 것까지 (LabVIEW TCP Read 의 CRLF 모드)
  lf    LF 까지
  cr    CR 까지
  fixed max_bytes 만큼
delimiter 로 칸을 나누고 points.index 가 그 칸이다. index 를 비우면 프레임 전체다.
points 를 비우면 프레임 전체를 line 이라는 이름으로 낸다.
"""
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

_NAME_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")


class Framing(str, Enum):
    CRLF = "crlf"
    LF = "lf"
    CR = "cr"
    FIXED = "fixed"


class PointType(str, Enum):
    BOOL = "bool"
    I64 = "i64"
    F64 = "f64"
    STR = "str"

    @property
    def numeric(self) -> bool:
        return self in (PointType.I64, PointType.F64)


class SocketPoint(BaseModel):
    """프레임 안의 칸 하나. index 가 없으면 구분자로 나누기 전의 한 줄이다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    index: int | None = None
    type: PointType = PointType.STR
    scale: float | None = None

    @model_validator(mode="after")
    def _check(self) -> "SocketPoint":
        if not self.name or any(ch not in _NAME_CHARS for ch in self.name):
            raise ValueError(f"포인트 이름은 영숫자/_/- 만 쓴다: {self.name!r}")
        if self.index is not None and self.index < 0:
            raise ValueError(f"{self.name}: index 는 0 이상")
        if self.scale is not None and not self.type.numeric:
            raise ValueError(f"{self.name}: scale 은 i64 / f64 에만 쓴다")
        return self


class SocketMapSettings(BaseModel):
    """소켓 맵 JSON 최상위. 주소와 포트는 SOCKET_HOST / SOCKET_PORT 에 둔다."""

    model_config = ConfigDict(extra="forbid")

    framing: Framing = Framing.CRLF
    max_bytes: int = Field(default=500, ge=1, le=1_000_000)
    encoding: str = "utf-8"
    # 칸 구분자. 빈 문자열이면 공백으로 나눈다. fixed 가 아니면 줄 끝 구분자는 여기 넣지 않는다
    delimiter: str = ","
    # 읽기 전에 보낼 문자열. 비우면 보내지 않는다. 줄 끝은 framing 에 맞춰 붙인다
    request: str | None = None
    points: list[SocketPoint] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "SocketMapSettings":
        try:
            "x".encode(self.encoding)
        except LookupError as e:
            raise ValueError(f"알 수 없는 encoding: {self.encoding}") from e
        if not self.points:
            self.points.append(SocketPoint(name="line", type=PointType.STR))
        names = [p.name for p in self.points]
        duplicated = sorted({n for n in names if names.count(n) > 1})
        if duplicated:
            raise ValueError(f"포인트 이름 중복: {duplicated}")
        return self
