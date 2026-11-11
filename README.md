# collector_robot_soket

로봇 TCP 소켓에서 프레임을 주기적으로 읽어 게이트웨이로 넘기는 컬렉터다. 접속과 폴링 루프, ZeroMQ 규약은 [collector-robot-modbus](https://github.com/CAMTIC-DATA-SKILL/collector-robot-modbus) 와 같고, 메모리 맵 자리에 프레임 맵이 있다.

## 아키텍처

```
로봇 TCP 소켓 ──프레임──▶ collector_robot_soket ──IPC(ZeroMQ)──▶ 게이트웨이
```

- 남향: `SOCKET_HOST`:`SOCKET_PORT` 에 붙어 맵의 framing 으로 프레임 하나를 읽고, 구분자로 나눈 칸을 샘플로 만든다.
- 북향: `collector.robot.{DEVICE_KEY}.{data|health|ack}` 로 보낸다. cmd 는 아직 처리하지 않고 `E-4102` ack 를 돌려준다.

테스트베드 SCARA 는 LabVIEW `TCP Read` 의 CRLF 모드, 최대 500바이트, 포트 5002 다. IP 는 VI 에 없다.

## 구성

```
main.py                      # 주기 읽기 → ZeroMQ data/health PUB, cmd SUB
config.py                    # .env 로딩. 환경 변수는 여기서만 읽는다
socket_map.json              # SCARA 프레임 맵
profiles/scara/              # 같은 맵
core/socket_client/          # TCP 세션, 프레임 자르기, 칸 디코딩
core/zeromq_client/          # 게이트웨이 IPC
script/smoke_socket.py       # 로컬 소켓 스모크
```

## 환경 준비

Python 3.10 이상.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` 의 `SOCKET_HOST` 만 현장 주소로 바꾼다.

## 실행

```bash
python main.py
```

시작 로그에 framing, 요청 문자열, 포인트 칸 번호가 나온다. 연결이 끊기거나 프레임이 `max_bytes` 를 넘으면 `RECONNECT_INTERVAL_SEC` 후 다시 붙는다. 칸이 없거나 타입이 다르면 그 포인트의 `error` 로 남고 소켓은 유지한다.

```bash
python -m core.zeromq_client --device-key scara-1
```

## 프레임 맵

주소와 포트는 맵에 넣지 않는다.

```json
{
  "framing": "crlf",
  "max_bytes": 500,
  "encoding": "utf-8",
  "delimiter": ",",
  "request": null,
  "points": [
    {"name": "line", "type": "str"},
    {"name": "seq", "index": 0, "type": "f64"}
  ]
}
```

| 필드 | 설명 |
| --- | --- |
| `framing` | `crlf` `lf` `cr` `fixed`. `crlf` 는 CR, LF, CRLF 중 먼저 오는 것까지 |
| `max_bytes` | 프레임 상한. `fixed` 는 이 길이만큼 읽는다 |
| `delimiter` | 칸 구분자. 빈 문자열이면 공백. 줄 끝 문자는 넣지 않는다 |
| `request` | 읽기 전에 보낼 문자열. 줄 끝은 framing 에 맞춰 붙인다. 없으면 보내지 않는다 |
| `index` | 0부터. 비우면 나누기 전 프레임 전체 |
| `type` | `bool` `i64` `f64` `str` |
| `scale` | 숫자 칸에만. 읽은 값에 곱한다 |

`points` 를 비우면 프레임 전체를 `line` 으로 하나 낸다.

## SCARA 칸 순서

`socket_map.json` 의 칸 번호는 LabVIEW `Robot-SCARA` 클러스터를 앞에서부터 펼친 순서다. VI 에 구분자와 칸 순서가 없어서 구분자는 쉼표로 두었다. 실제 줄이 다르면 `delimiter` 와 `index` 만 고친다. `line` 은 항상 원문이다.

`line`, Timestamp, Model, Seq, Online, MotorState, PowerMode, TaskState, Waypoint, J1–J4 의 Position·Torque, X, Y, Z, Rz, LastError.

## data 메시지

토픽 `collector.robot.{DEVICE_KEY}.data`.

```json
{
  "msg_type": "data",
  "collector_address": "scara-1",
  "msg_body": {
    "device_key": "scara-1",
    "sample_ms": 1760236380000,
    "samples": [
      {"name": "seq", "index": 2, "type": "f64", "value": 3.0, "error": null}
    ],
    "sockets": []
  }
}
```

| 코드 | 의미 |
| --- | --- |
| `E-1001` / `E-1002` / `E-1003` | 연결 실패 / 상대가 닫음 / 타임아웃. health 로 알리고 재연결한다 |
| `E-2203` | 그 칸이 프레임에 없다 |
| `E-3001` | 구분자가 상한 안에 없거나 글자 디코딩 실패. 재연결한다 |
| `E-4102` | 아직 처리하지 않는 cmd |

## 스모크 테스트

```bash
python script/smoke_socket.py
```

로컬 소켓으로 CRLF 두 줄, 스케일, 없는 칸, 상한 초과, 연결 종료, 요청 전송을 본다. 마지막 줄이 `== PASS n/n ==` 이면 성공이다.
