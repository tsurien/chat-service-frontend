"""화면 여러 곳에서 같이 쓰는 설정과 백엔드 호출 함수.

오류 메시지를 여기 한 곳에서만 만든다. 화면마다 제각각 문구를 쓰면
같은 상황인데 다르게 보이고, 나중에 고칠 때 빠뜨리는 곳이 생긴다.
"""

import httpx
import json
import os
import streamlit as st

try:
    _backend_url_secret = st.secrets.get("BACKEND_URL")
except Exception:
    _backend_url_secret = None

BACKEND_URL = _backend_url_secret or os.environ.get(
    "BACKEND_URL", "http://127.0.0.1:8000"
)

HTTP_TIMEOUT = 60
SERVICE_NAME = "면접 연습 챗봇"

class ApiError(Exception):
    """화면에 그대로 보여줄 수 있는 오류 메시지를 담는다.
    httpx 가 던지는 예외 이름(ConnectError 등)이 아니라 무엇을 하면 되는지가 담긴 문장으로 바꿔서 돌려준다.
    """
class SessionExpired(ApiError):
    """로그인이 풀린 상태.

    ApiError 를 물려받는 것이 중요하다. 아직 처리를 안 붙인 화면에서도
    최소한 오류로는 잡힌다. 그러나 화면 전체를 로그인으로 되돌려야 하는
    상황이라 따로 알아볼 수 있게 이름을 나눠 둔다.
    """

# 여러번 나눠서 받기
def stream_answer(path: str, payload: dict | None = None, headers: dict | None = None):
    """SSE 응답을 글자 조각으로 하나씩 내어준다.

    api() 와 나눠 둔 이유는 반환하는 것이 다르기 때문이다.
    api() 는 완성된 JSON 을 주고, 이 함수는 아직 안 끝난 응답을 조금씩 준다.

    스트림이 시작된 뒤의 실패는 상태 코드로 알 수 없다. 헤더가 이미 나갔기 때문이다.
    그래서 서버가 error 이벤트로 보내고, 여기서 ApiError 로 바꿔 올린다.
    """
    try:
        with httpx.stream(
            "POST", 
            f"{BACKEND_URL}{path}", json=payload or {}, 
            headers=headers,
            timeout=HTTP_TIMEOUT
        ) as response:
            if response.status_code == 401:
                response.read()
                raise SessionExpired(
                    "로그인이 만료되었습니다. 기록은 그대로 있으니 다시 로그인해 주세요."
                )
            if response.status_code >= 400:
                response.read()
                raise ApiError(f"요청이 실패했습니다 (상태 코드 {response.status_code}).")

            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                event = json.loads(line.removeprefix("data: "))
                if "error" in event:
                    raise ApiError(f"답변을 만들지 못했습니다. {event['error']}")
                if event.get("done"):
                    return
                yield event["text"]
    except httpx.ConnectError:
        raise ApiError("백엔드 서버에 연결할 수 없습니다.")
    except httpx.TimeoutException:
        raise ApiError("응답이 너무 오래 걸려 중단했습니다. 다시 시도해 보세요.")

# 한번에 받기
def api(method: str, path: str, **kwargs):
    """백엔드를 호출하고 JSON 을 돌려준다. 실패하면 ApiError 를 던진다."""
    try:
        response = httpx.request(
            method, f"{BACKEND_URL}{path}", timeout=HTTP_TIMEOUT, **kwargs
        )
    except httpx.ConnectError:
        raise ApiError("백엔드 서버에 연결할 수 없습니다.")
    except httpx.TimeoutException:
        raise ApiError("서버가 제때 응답하지 않았습니다. 잠시 후 다시 시도하세요.")

    if response.status_code == 401:
        # 토큰이 만료됐거나 잘못된 상태다. 토큰 수명은 60분이라
        # 하루 수업 중에 반드시 한 번은 만난다.
        # 주의: 이것을 빈 목록으로 처리하면 화면에 "대화가 없습니다" 가 뜬다.
        #      사용자는 자기 기록이 사라진 줄 안다.
        raise SessionExpired(
            "사용 시간이 만료되었습니다. 다시 로그인해 주세요."
        )

    if response.status_code == 422:
        # 상태 코드만 보여주면 무엇을 고쳐야 할지 알 수 없다.
        raise ApiError(
            "입력한 값의 형식이 올바르지 않습니다. "
        )

    if response.status_code == 503:
        # 모델 호출이 실패한 경우다. 백엔드가 detail 에 원인을 담아서 보낸다.
        # 17일차에 가장 흔한 원인은 하루 요청 한도 초과(429)다.
        # 상태 코드만 보여주면 "왜 갑자기 안 되지" 로 끝나고 스스로 못 고친다.
        detail = response.json().get("detail", "")
        if "429" in detail or "RESOURCE_EXHAUSTED" in detail:
            raise ApiError(
                "오늘 쓸 수 있는 AI 요청 횟수를 다 썼습니다. "
                "무료 등급은 모델마다 하루 요청 수가 정해져 있습니다. "
                "내일 다시 시도하거나 강사에게 알리세요."
            )
        raise ApiError(f"답변을 만들지 못했습니다. {detail}")

    if response.status_code >= 400:
        raise ApiError(f"요청이 실패했습니다 (상태 코드 {response.status_code}).")

    return response.json() if response.content else None

def conversation_label(conversation: dict) -> str:

    """대화목록(프론트엔드 선택위젯)에 보여줄 한 줄.

    제목만 쓰면 같은 직무로 두 번 연습했을 때 둘을 구분할 수 없다.
    만든 시각과 id 앞자리를 붙여서 눈으로 구분되게 한다.
    """
    title = conversation.get("title") or "(제목 없음)"
    created = conversation["created_at"][:16].replace("T", " ")
    return f"{title} · {created} · {conversation['id'][:8]}"

def auth_headers() -> dict:
    """로그인 정보를 요청에 붙여주는 헤더를 생성합니다"""
    return {"Authorization":f"Bearer {st.session_state.access_token}"}
    # return {"Authorization": {st.session_state.access_token}}
