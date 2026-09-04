import streamlit as st
from common import ( ApiError, 
                        api, 
                        conversation_label,
                        SessionExpired, 
                        auth_headers,
                        SERVICE_NAME,
                        stream_answer
                    )   

# 상태 종류
# 1. 비로그인
# 2. 로그인 + 대화목록 없음
# 3. 로그인 + 대화목록 있음 + 대화선택 안함 > 제일 위의 대화 선택
# 4. 로그인 + 대화목록 있음 + 대화선택 있음 + 메시지 없음 > 예시질문 출력
# 5. 로그인 + 대화목록 있음 + 대화선택 있음 + 메시지 있음 > 대화 화면 출력 + 꼬리질문 출력
# 6. 세션 만료 > 토큰 60분 초과 > 왜 풀렸는지+로그인 안내

st.set_page_config(page_title=SERVICE_NAME)

#세션에 사용자id, 대화id를 저장한다.
#st.session_state.setdefault("user_id", "")
st.session_state.setdefault("access_token", "") #RLS 적용한 /me 라우터용
st.session_state.setdefault("user_email", "")
st.session_state.setdefault("conversation_id", None)
# st.session_state.setdefault("tone", "친절하게")
# st.session_state.setdefault("length", "보통")

# 버튼으로 보낼 질문을 잠시 담아두는 곳. 버튼 안에서 바로 보내면
# 화면이 다시 그려지는 도중이라 결과가 화면에 안 나타난다.
st.session_state.setdefault("pending_question", None)
st.session_state.setdefault("expired_notice", "")
st.session_state.setdefault("failed_question", None)

# 시작 질문 예시
EXAMPLE_QUESTIONS = [
    "면접을 시작해 주세요.",
    "1분 자기소개를 해보겠습니다.",
    "제 이력서에서 가장 많이 받을 질문이 뭘까요?",
]

@st.cache_data(ttl=300)
def load_options() -> dict:
    """선택지는 백엔드에서 받아온다.

    화면에 목록을 직접 적어두면 백엔드의 표와 두 곳에서 관리하게 된다.
    한쪽에 톤을 추가하고 다른 쪽을 잊으면, 버튼은 있는데 아무 효과가 없다.
    """
    return api("GET", "/chat/options")

def render_sidebar(options: dict, conversations: list) -> None:
    with st.sidebar :
        #로그인한 사용자 이메일 출력
        st.caption(st.session_state.user_email) 
        if st.button('로그아웃'):
            sign_out()
        
        st.divider()
            
        st.subheader("면접 연습용 대화 기록")
        
        # 대화가 있을 때   
        if conversations:
            labels = {c['id'] : conversation_label(c) for c in conversations}  #리스트 컴프리헨션 코드
            ids = list(labels)
            
            current = st.session_state.conversation_id
            
            #선택위젯을 그리고, 사용자가 특정 대화를 선택하면 selected에 저장한다
            selected = st.selectbox(
                    "이전 면접 연습 대화 내역입니다.",
                    options = ids,
                    format_func = lambda cid : labels[cid],
                    index = ids.index(current) if current in ids else 0,
                    key = "conversation_select"
                )
            # 세션에 사용자가 선택한 대화id를 저장한다.
            st.session_state.conversation_id = selected
            
            # 기존 대화 제목 변경, 삭제 추가
            new_title = st.text_input("새 이름", key="rename_input")
            rename_column, delete_column = st.columns(2)
            if rename_column.button("이름 변경", use_container_width=True) and new_title:
                api(
                    "PATCH",
                    f"/me/conversations/{selected}",
                    json={"title": new_title},
                    headers=auth_headers(),
                )
                st.session_state.converersation_select = selected
                st.rerun()
            if delete_column.button("삭제", use_container_width=True):
                api("DELETE", f"/me/conversations/{selected}", headers=auth_headers())
                st.session_state.conversation_id = None
                st.rerun()
        else:
            st.caption("면접 준비 대화를 시작하세요")
            # 새로운 대화 시작 버튼
            
        st.divider()
        
        job_title = st.text_input("면접연습 직무", placeholder='예: AI Agent 개발자')
        # 대화 생성 버튼 클릭 & 직무 입력 확인
        if st.button("새 면접 연습 시작", use_container_width=True) and job_title : 
            # 대화 생성 엔드포인트 호출
            created = api(
                "POST",
                "/me/conversations",
                json={"title": job_title},
                headers=auth_headers(),
            )
        
            # 새로 생성한 대화id 를 세션에 저장
            st.session_state.conversation_id = created['id']
            st.rerun()
        
        #면접관 설정 영역
        st.divider()
        st.subheader('면접관 타입 설정')
        st.radio("말투", options['tones'], key="tone", horizontal=False)
        st.radio("답변 길이", options['lengths'], key="length", horizontal=True)
        st.caption("설정 값은 새로운 질문부터 적용됩니다.")

def render_empty(message: str, hint: str)-> None:
    st.info(message)
    st.caption(hint)

def ask(conversation_id: str, question: str) -> None:
    """질문을 제미나이에게 보내고, 응답을 받는다"""
    
    # user 메시지 먼저 출력
    with st.chat_message("user"):
        st.write(question)
    
    # 어시스턴트 메시지는 스트림으로 다 올때까지 출력
    with st.chat_message("assistant"):
        try:
            # st.write_stream 은 조각을 받아 화면에 이어 붙이고, 커서도 그려준다.
            st.write_stream(
                stream_answer(
                    f"/conversations/{conversation_id}/chat",
                    {
                        "content": question,
                        "tone": st.session_state.tone,
                        "length": st.session_state.length,
                    },
                    auth_headers(),
                )
            )
        except ApiError as error:
            # 실패한 질문을 기억해 둔다. 다시 시도 버튼이 이것을 쓴다.
            # 사용자가 긴 답변을 다시 타이핑하게 만들면 안 된다.
            st.session_state.failed_question = question
            st.error(str(error))
            return

    st.session_state.failed_question = None
    st.rerun()

def render_follow_ups() -> None:
    """직전 답변을 두고 이어서 할 수 있는 행동.

    주의: 오늘은 모델이 이전 대화를 기억하지 못한다(19일차 주제).
    그래서 직전 답변을 질문 안에 넣어서 보낸다. 맥락은 결국 프롬프트로 들어간다.
    """
    st.caption("이어서")
    actions = {
        "더 자세히": f"방금 한 이 말을 예시를 들어 더 자세히 설명해 주세요.",
        "간단하게": f"방금 한 이 말을 세 문장으로 줄여 주세요.",
        "다음 질문": "다음 면접 질문을 하나 주세요.",
    }
    columns = st.columns(len(actions))
    for column, (label, question) in zip(columns, actions.items()):
        if column.button(label, use_container_width=True):
            st.session_state.pending_question = question
            st.rerun()    

# 최대메시지수(20) , 현재 메시지 수 중 작은 값 반환
def _remembered_count(messages: list, max_history: int) -> int:
    """모델에게 실제로 갈 메시지 수. 백엔드 _build_history 와 같은 순서로 센다."""
    for index in range(len(messages) - 1, -1, -1):
        if messages[index]["role"] == "system":
            messages = messages[index + 1 :]
            break
    usable = [m for m in messages if m["role"] in ("user", "assistant")]
    return min(len(usable), max_history)

def render_context_controls(conversation_id: str, messages: list, max_history: int) -> None:
    """면접관이 무엇을 기억하는지 보여주고, 끊을 수 있게 한다.

    사용자는 모델이 무엇을 참고하는지 볼 수 없다. 화면이 말해주지 않으면
    "왜 아까 한 말을 기억 못하지" 또는 반대로 "왜 지운 얘기를 계속 하지"가 된다.
    """
    remembered = _remembered_count(messages, max_history)
    reset_column, info_column = st.columns([1, 3])
    if reset_column.button("맥락 초기화", use_container_width=True):
        api("POST", f"/conversations/{conversation_id}/reset-context",
            headers=auth_headers(),)
        st.rerun()
    info_column.caption(
        f"면접관은 지금 이 대화의 최근 {remembered}개를 기억합니다 "
        f"(최대 {max_history}개). 초기화해도 기록은 남습니다."
    )

def render_conversation(conversation_id: str, max_history: int) -> None:
    """화면 가운데 영역: 주고받은 메시지 내용과 새로운 메시지 입력칸."""
    
    # 메시지 내역 가져오기
    messages = api("GET", f"/conversations/{conversation_id}/messages",
                   headers=auth_headers())
    feedback = api("GET", f"/conversations/{conversation_id}/feedback", 
                   headers=auth_headers()) or {}
    
    # 저장된 메시지가 없으면 안내 힌트 제공
    if not messages:
        render_empty(
            "아직 주고받은 내용이 없습니다.",
            "아래 입력칸에 첫 답변을 적어보세요.",
        )
        #예시 질문을 출력합니다.
        render_example(conversation_id)

    # 메시지 목록 출력
    #for message in messages:
    last_index = len(messages) - 1
    for index, message in enumerate(messages):
        if message['role'] == 'system':
            st.divider()
            st.caption(message['content'])
            continue #그 다음 메시지로 간다
       
        with st.chat_message(message["role"]):
            st.write(message["content"])
            
            if message['role'] == 'assistant':
                if index == last_index:
                    # 다시 생성은 마지막 답변에만 붙인다. 중간 답변을 다시 만들면
                    # 그 뒤의 대화와 앞뒤가 안 맞게 된다.
                    if st.button("다시 생성", key=f"regen_{message['id']}"):
                        regenerate(conversation_id)
            
    # 컨텍스트 초기화 출력        
    render_context_controls(conversation_id,
                            messages,
                            max_history
                            )
    
    # 메시지 목록이 있고, 목록의 마지막 메시지의 'role' 이 assistant 일때
    if messages and (messages[-1]['role']=='assistant'):
        render_follow_ups()
    
    #세션에 담긴 질문이 있으면 답변을 요청
    if st.session_state.pending_question :
        question = st.session_state.pending_question
        st.session_state.pending_question = None
        ask(conversation_id, question)
    
    if st.session_state.failed_question:
        # 답을 못 받은 상태다. 같은 질문을 그대로 다시 보낼 수 있게 한다.
        st.warning("답변을 받지 못했습니다.")
        retry_column, cancel_column, _ = st.columns([1, 1, 6])
        if retry_column.button("다시 시도"):
            question = st.session_state.failed_question
            st.session_state.failed_question = None
            ask(conversation_id, question)
        if cancel_column.button("취소"):
            st.session_state.failed_question = None
            st.rerun()
    # 새로운 메시지 입력 위젯 출력
    if answer := st.chat_input("답변을 입력하세요"):
        ask(conversation_id, answer)

def regenerate(conversation_id: str) -> None:
    """마지막 답변을 지우고 새로 받는다.

    다시 시도(Retry)와 다르다.
      다시 시도  — 실패한 요청을 그대로 다시 보낸다. 답이 없는 상태다
      다시 생성  — 성공한 답이 마음에 안 들어 새로 받는다. 기존 답을 지운다
    """
    with st.chat_message("assistant"):
        try:
            st.write_stream(
                stream_answer(
                    f"/conversations/{conversation_id}/regenerate",
                    # 질문은 다시 보내지 않는다. 서버가 마지막 질문을 그대로 쓴다.
                    # 말투와 길이만 보낸다 — 바꿔놓고 다시 생성하는 경우가 많다.
                    {
                        "tone": st.session_state.tone,
                        "length": st.session_state.length,
                    },
                    auth_headers(),
                )
            )
        except ApiError as error:
            st.error(str(error))
            return
    st.rerun()

def render_example(conversation_id: str) -> None:
    """새로운 대화를 시작한 상태에서 출발 질문을 제시하는 함수"""
    st.caption("아래 질문 중에서 선택해보세요")
    columns = st.columns(len(EXAMPLE_QUESTIONS))    #예시 질문 목록에 따른 영역 설정
    for col, question in zip(columns, EXAMPLE_QUESTIONS):
        # 클릭한 버튼의 질문을 세션 변수에 저장합니다.
        if col.button(question, use_container_width=True) :
            st.session_state.pending_question = question
            st.rerun()

def render_login() -> None:
    """비로그인 상태의 화면 - 전체영역"""
    # 1. 세션만료 확인
    if st.session_state.expired_notice:
        st.warning(st.session_state.expired_notice)
    
    st.write("면접 준비를 위한 직무별 면접 연습 서비스입니다.  사용 기록은 개인 계정에 저장됩니다")
    
    # 2. email, password 입력
    email = st.text_input("이메일", placeholder="you@example.com")
    password = st.text_input("비밀번호", type="password")

    # 3. api /auth/login, /auth/signup 호출
    login_column, signup_column = st.columns(2)
    
    # 버튼 처리
    action = None
    
    if login_column.button("로그인", use_container_width=True) :
        #login 호출
        action = "login"
    
    if signup_column.button("회원가입", use_container_width=True) :
        # signup 호출
        action = "signup"
    
    # api 호출
    if not action : 
        return
    if not email or not password:
        st.error("이메일과 비밀번호를 모두 입력하세요.")
        return
    try:
        result = api(
            "POST", f"/auth/{action}", json={"email": email, "password": password}
        )
    except ApiError as error:
        st.error(str(error))
        return
    
    if not result.get("access_token"):
        # 가입은 됐는데 토큰이 없는 경우가 있다 (이메일 확인이 켜져 있을 때).
        st.error("가입은 되었지만 바로 로그인되지 않았습니다. 강사에게 알리세요.")
        return
    
    # 4. 로그인 결과에서 token, email 세션에 저장
    st.session_state.access_token = result["access_token"]
    st.session_state.user_email = result["email"]
    st.session_state.expired_notice = None #세션 초기화

def sign_out(notice: str | None=None) -> None:
    """로그인 관련 상태를 한 번에 지운다."""
    st.session_state.access_token = None
    st.session_state.user_email = None
    st.session_state.conversation_id = None
    st.session_state.pending_question = None
    st.session_state.expired_notice  = notice
    st.session_state.failed_question = None
    
    st.rerun()  #로그인 화면 렌더링

def render_signed_in() -> None:
    """로그인 이후 화면을 생성하는 함수"""
    
    # 브라우저 화면에 렌더링하는 영역        
    # 1. 화면 구성에 필요한 환경정보 설정 - 엔드포인트 호출을 위한 
    options = load_options()
    
    # 라디오 버튼의 초기값. 백엔드가 알려준 기본값을 쓴다.
    st.session_state.setdefault("tone", options["default_tone"])
    st.session_state.setdefault("length", options["default_length"])

    #3. 사이드 바 출력
    # 세션의 토큰으로 대화 목록 조회
    conversations = api("GET", "/me/conversations", headers=auth_headers())
    
    #대화목록으로 사이드바 렌더링
    render_sidebar(options, conversations)
    
    #대화영역 렌더링
    if not conversations :
        render_empty(
                    "아직 연습 기록이 없습니다",
                    "왼쪽에서 지원할 직무를 적고 `새 면접 시작` 을 누르세요.",
                )
    elif not st.session_state.conversation_id :
        render_empty("연습할 면접을 고르세요.",
                 "왼쪽 `지난 연습` 에서 하나를 선택하면 됩니다.")
    else:
        render_conversation(st.session_state.conversation_id,
                            options["max_history_messages"])

# 4. 화면 가운데 출력
st.title(SERVICE_NAME)

# 로그인한 세션 정보가 있을 때
try:
    if st.session_state.access_token :
        render_signed_in()
        #st.write(f"{st.session_state.user_email} 로 로그인했습니다.")
    else :
        #로그인 페이지 렌더링
        render_login()
except SessionExpired as error:
    # 세션 정보 만료 > sign_out()
    sign_out(str(error))
except ApiError as error:
    st.error(str(error))
