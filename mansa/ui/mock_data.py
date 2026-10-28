"""화면 확인용 목데이터.

features/ 기능이 붙기 전까지 화면이 이 값을 사용한다.
각 함수의 docstring에 나중에 바꿔 끼울 기능 함수 자리를 적어 둔다.
"""

import copy
import time
from dataclasses import dataclass, field

MODELS = ["[모델 A]", "[모델 B]", "[모델 C]"]
DEPARTMENTS = ["유지보수팀", "안전팀", "검사·품질팀"]

# ---------------------------------------------------------------- 로그인
MOCK_DELAY = 1.2  # 시연용 대기 시간(초): 실제 처리 시간을 흉내 낸다


def wait(seconds: float | None = None) -> None:
    """실제 검색·생성·업로드 처리 시간을 흉내 낸다. 진짜 기능을 연결하면 이 호출을 지운다."""
    time.sleep(MOCK_DELAY if seconds is None else seconds)


MOCK_ACCOUNTS = {
    "user": {"name": "홍길동", "dept": "유지보수팀"},
    "admin": {"name": "김안전", "dept": "관리자"},
}


def mock_login(user_id: str, password: str, role: str) -> tuple[dict | None, str]:
    """아이디·비밀번호가 비어 있지 않으면 해당 권한의 예시 계정으로 로그인한다.

    실제 계정 확인은 하지 않는다. features/auth 의 인증 함수가 생기면 그 함수로 바꾼다.
    반환값은 (회원 정보 또는 None, 오류 문구)다.
    """
    if not user_id.strip() or not password.strip():
        return None, "아이디와 비밀번호를 입력해 주세요"
    account = MOCK_ACCOUNTS[role]
    return {"id": user_id.strip(), "role": role, **account}, ""


# ---------------------------------------------------------------- 기술 Q&A
EXAMPLE_QUESTIONS = ["메인 로프 점검", "브레이크 라이닝 교체", "도어 센서 조정"]

FREQUENT_TASKS = [
    {"place": "카 상부 · 기계실", "title": "메인 로프 점검", "meta": "문서 6개 · 3개 부서"},
    {"place": "기계실", "title": "브레이크 라이닝 교체", "meta": "문서 4개 · 2개 부서"},
    {"place": "승강장", "title": "도어 센서 조정", "meta": "문서 3개 · 2개 부서"},
    {"place": "피트", "title": "비상정지장치 시험", "meta": "문서 5개 · 3개 부서"},
]

RECENT_QUESTIONS = [
    {"title": "[모델 A] 메인 로프 교체 기준", "meta": "오늘 10:24 · 근거 5개"},
    {"title": "권상기 브레이크 갭 측정 방법", "meta": "오늘 10:11 · 근거 3개"},
    {"title": "비상정지장치 작동 시험 순서", "meta": "오늘 09:58 · 근거 4개"},
]

RECENT_CHANGES = [
    {"title": "[모델 B] 유지보수 매뉴얼", "meta": "10/23 · 기술 문서 · 유지보수팀"},
    {"title": "사내 승강기 작업 안전규정", "meta": "10/23 · 안전 문서 · 안전팀"},
    {"title": "KOSHA GUIDE [번호] 승강기 작업", "meta": "10/22 · 안전 문서 · 안전팀"},
]


@dataclass
class Source:
    """답변 근거 하나 (근거 목록과 근거 원문 창에 함께 쓰인다)."""

    kind: str  # "매뉴얼" | "안전 조항"
    dept: str
    title: str
    loc: str
    heading: str
    lines: list[str] = field(default_factory=list)
    highlight: str = ""


SOURCES = [
    Source(
        "매뉴얼",
        "유지보수팀",
        "[매뉴얼명] 5.3.2",
        "p.42",
        "5.3 메인 로프 점검",
        [
            "점검은 카를 최상층 근처에 세운 상태에서 실시한다.",
            "측정값은 점검표에 기록하고 교체 기준과 비교한다.",
        ],
        "5.3.2 로프 마모 점검: 점검 운전으로 로프 전 길이를 확인하고, "
        "소선 끊김과 직경 감소를 측정한다.",
    ),
    Source(
        "매뉴얼",
        "유지보수팀",
        "[매뉴얼명] 표 5-2",
        "p.44",
        "표 5-2 메인 로프 사양",
        ["공칭 직경, 교체 기준 직경, 점검 주기를 모델별로 정리한 표다."],
        "교체 기준 직경: [값] mm 미만이면 교체한다.",
    ),
    Source(
        "안전 조항",
        "안전팀",
        "산업안전보건기준 규칙 제○○조",
        "1항 2호",
        "제○○조 (와이어로프 등)",
        ["사업주는 다음에 해당하는 와이어로프를 사용해서는 안 된다."],
        "지름 감소가 공칭지름의 [값]%를 초과하는 것",
    ),
    Source(
        "안전 조항",
        "안전팀",
        "KOSHA GUIDE [번호]",
        "4.2",
        "4.2 카 상부 작업",
        ["카 상부 작업 전 점검 운전 스위치와 정지 스위치를 확인한다."],
        "카 상부에서는 추락 방지 조치를 하고 작업한다.",
    ),
]


@dataclass
class Answer:
    """기술 Q&A 답변 한 건 (① 절차 ② 사양 ③ 안전 요건 ④ 기준 차이)."""

    question: str
    model: str
    place: str
    procedure: list[str]
    specs: list[tuple[str, str]]
    diffs: list[tuple[str, str]]
    safety: list[tuple[str, str]]
    sources: list[Source]


def _sample_answer(question: str, model: str) -> Answer:
    """Figma 답변 화면과 같은 예시 답변을 만든다."""
    return Answer(
        question=question,
        model=model or "[모델 A]",
        place="카 상부 · 기계실",
        procedure=[
            "카를 최상층 근처에 세우고 기계실 주전원을 차단합니다.",
            "카 상부에서 점검 운전으로 로프를 돌리며 마모·소선 끊김을 확인합니다.",
            "로프 직경을 세 곳 이상 측정해 점검표에 기록합니다.",
        ],
        specs=[
            ("공칭 직경", "[값] mm"),
            ("교체 기준 직경", "[값] mm 미만"),
            ("점검 주기", "[값]개월"),
        ],
        diffs=[("매뉴얼", "[값] mm 미만 교체"), ("안전 기준", "공칭 대비 [값]% 초과 감소")],
        safety=[
            (
                "카 상부 작업 시 추락 방지 조치를 해야 합니다.",
                "산업안전보건기준 규칙 제○○조 제1항 제2호",
            ),
            ("기계실 회전부의 끼임 방지 덮개를 확인합니다.", "KOSHA GUIDE [번호] 4.2"),
            ("전원을 차단한 뒤 잠금장치와 표지를 붙입니다.", "산업안전보건기준 규칙 제○○조"),
        ],
        sources=SOURCES,
    )


OUT_OF_SCOPE_WORDS = ("맛집", "날씨", "주식", "영화", "점심")
CLARIFY_PARTS = ["권상기 브레이크", "비상정지장치"]


def mock_ask(question: str, model: str) -> dict:
    """질문에 대한 예시 결과를 돌려준다.

    결과 종류: answer(답변) / clarify(모델이 없어 되묻기) / no_answer(문서 범위 밖).
    features/llm·retrieval 의 기술 Q&A 처리 함수가 생기면 이 함수 자리를 바꾼다.
    """
    text = question.strip()
    if any(word in text for word in OUT_OF_SCOPE_WORDS):
        return {"type": "no_answer"}
    model = model or _model_in(text)
    if not model:
        return {"type": "clarify", "models": MODELS, "parts": CLARIFY_PARTS}
    return {"type": "answer", "answer": _sample_answer(text, model)}


def _model_in(text: str) -> str:
    """질문 글에 '[모델 X]' 처럼 등록된 모델 이름이 있으면 그 이름을 돌려준다."""
    return next((m for m in MODELS if m in text), "")


def mock_answer_for(question: str, model: str) -> Answer:
    """되묻기에서 모델을 고른 뒤 바로 답변을 만든다."""
    return _sample_answer(question, model)


# ---------------------------------------------------------------- 질문 기록
HISTORY = [
    {
        "day": "오늘",
        "time": "10:24",
        "title": "[모델 A] 메인 로프 교체 기준",
        "model": "[모델 A]",
        "task": "메인 로프 교체",
        "count": 3,
    },
    {
        "day": "오늘",
        "time": "10:11",
        "title": "권상기 브레이크 갭 측정 방법",
        "model": "[모델 A]",
        "task": "브레이크 점검",
        "count": 2,
    },
    {
        "day": "오늘",
        "time": "09:58",
        "title": "비상정지장치 작동 시험 순서",
        "model": "[모델 B]",
        "task": "비상정지장치 시험",
        "count": 4,
    },
    {
        "day": "오늘",
        "time": "09:40",
        "title": "도어 센서 감도 조정 값",
        "model": "[모델 A]",
        "task": "도어 센서 조정",
        "count": 1,
    },
    {
        "day": "오늘",
        "time": "09:32",
        "title": "피트 작업 전 확인할 것",
        "model": "",
        "task": "피트 점검",
        "count": 2,
    },
    {
        "day": "오늘",
        "time": "09:15",
        "title": "주로프 소선 파단 허용 개수",
        "model": "",
        "task": "메인 로프 점검",
        "count": 1,
    },
    {
        "day": "10/23",
        "time": "10/23",
        "title": "카 도어 클로저 교체 순서",
        "model": "[모델 B]",
        "task": "도어 점검",
        "count": 2,
    },
    {
        "day": "10/22",
        "time": "10/22",
        "title": "기계실 환기 기준",
        "model": "",
        "task": "기계실 점검",
        "count": 1,
    },
]

FOLLOW_UPS = ["교체 주기도 알려줘", "측정할 때 필요한 공구는?", "작업 전 안전 확인 사항은?"]


def history_turns(index: int) -> list[dict]:
    """질문 기록 한 건을 기술 Q&A 대화(turns)로 펼친다.

    모델 없이 시작한 대화는 되묻기를 거쳐 [모델 A] 로 답한 것으로 보여 준다.
    features 의 대화 기록 조회 함수가 생기면 이 함수 자리를 바꾼다.
    """
    item = HISTORY[index]
    turns = []
    model = item["model"]
    if not model:
        turns.append({"q": item["title"], "kind": "clarify"})
        model = MODELS[0]
    turns.append(
        {"q": item["title"], "kind": "answer", "answer": _sample_answer(item["title"], model)}
    )
    for question in FOLLOW_UPS[: item["count"] - 1]:
        turns.append({"q": question, "kind": "answer", "answer": _sample_answer(question, model)})
    return turns


# ---------------------------------------------------------------- 문서 · 기준정보 · 회원
DOCUMENTS = [
    {
        "title": "[모델 A] 유지보수 매뉴얼",
        "type": "기술 문서",
        "dept": "유지보수팀",
        "status": "완료",
        "date": "10/21",
    },
    {
        "title": "[모델 A] 사양서",
        "type": "기술 문서",
        "dept": "유지보수팀",
        "status": "완료",
        "date": "10/21",
    },
    {
        "title": "산업안전보건기준에 관한 규칙 (발췌)",
        "type": "안전 문서",
        "dept": "안전팀",
        "status": "완료",
        "date": "10/22",
    },
    {
        "title": "KOSHA GUIDE [번호] 승강기 작업",
        "type": "안전 문서",
        "dept": "안전팀",
        "status": "처리 중",
        "date": "10/23",
    },
    {
        "title": "사내 승강기 작업 안전규정 (스캔본)",
        "type": "안전 문서",
        "dept": "안전팀",
        "status": "실패",
        "date": "10/23",
    },
    {
        "title": "[모델 B] 유지보수 매뉴얼",
        "type": "기술 문서",
        "dept": "유지보수팀",
        "status": "처리 중",
        "date": "10/23",
    },
]

DOC_TYPES = {"기술 문서": "매뉴얼 · 사양서", "안전 문서": "법규 · 지침 · 사내 규정"}

DEPT_INFO = [
    {"name": "유지보수팀", "desc": "매뉴얼 · 사양서 관리"},
    {"name": "안전팀", "desc": "법규 · 지침 · 사내 규정"},
    {"name": "검사·품질팀", "desc": "검사 절차서 · 체크리스트"},
]

MODEL_SPECS = [
    {
        "id": "M-001",
        "name": "[모델 A]",
        "maker": "[제조사]",
        "speed": "[값] m/min",
        "load": "[값] kg",
        "use": "승객용",
        "docs": 3,
    },
    {
        "id": "M-002",
        "name": "[모델 B]",
        "maker": "[제조사]",
        "speed": "[값] m/min",
        "load": "[값] kg",
        "use": "화물용",
        "docs": 2,
    },
    {
        "id": "M-003",
        "name": "[모델 C]",
        "maker": "[제조사]",
        "speed": "[값] m/min",
        "load": "[값] kg",
        "use": "승객용",
        "docs": 0,
    },
]

RELATIONS = [
    {"work": "메인 로프 점검", "places": ["카 상부", "기계실"], "hazards": ["추락", "끼임"]},
    {"work": "브레이크 라이닝 교체", "places": ["기계실"], "hazards": ["끼임", "감전"]},
    {"work": "도어 센서 조정", "places": ["승강장", "카 상부"], "hazards": ["추락", "끼임"]},
    {"work": "비상정지장치 시험", "places": ["피트", "카 상부"], "hazards": ["추락", "낙하"]},
    {"work": "권상기 급유", "places": ["기계실"], "hazards": ["끼임"]},
]

TAXONOMY = {
    "부위": ["메인 로프", "브레이크 라이닝", "도어 센서", "비상정지장치", "권상기"],
    "작업": [r["work"] for r in RELATIONS],
    "작업 위치": ["카 상부", "기계실", "승강장", "피트"],
    "위험 유형": ["추락", "끼임", "감전", "낙하"],
}

SYNONYMS = [
    ("와이어로프", "메인 로프"),
    ("권상기", "트랙션 머신"),
    ("카", "승강기 칸"),
    ("가버너", "조속기"),
    ("브레이크 슈", "브레이크 라이닝"),
]

MEMBERS = [
    {
        "name": "이OO",
        "id": "admin01",
        "dept": "안전팀",
        "role": "관리자",
        "date": "10/20",
    },
    {
        "name": "박OO",
        "id": "user01",
        "dept": "유지보수팀",
        "role": "사용자",
        "date": "10/21",
    },
    {
        "name": "김OO",
        "id": "user02",
        "dept": "유지보수팀",
        "role": "사용자",
        "date": "10/21",
    },
    {
        "name": "최OO",
        "id": "user03",
        "dept": "검사·품질팀",
        "role": "사용자",
        "date": "10/22",
    },
    {
        "name": "정OO",
        "id": "user04",
        "dept": "유지보수팀",
        "role": "사용자",
        "date": "10/22",
    },
]


def new_store() -> dict:
    """로그인한 사람마다 따로 쓰는 목데이터 묶음(문서·부서·회원).

    화면에서 추가·삭제해도 다른 사람 화면에는 영향이 없다. DB 가 붙으면 없어진다.
    """
    return copy.deepcopy({"docs": DOCUMENTS, "depts": DEPT_INFO, "members": MEMBERS})


# ---------------------------------------------------------------- 고객센터
SUPPORT_GREETING = "안녕하세요. MANSA 사용법을 물어보세요. 해결이 안 되면 관리자와 연결해 드려요."
SUPPORT_CHIPS = ["문서는 어떻게 올려요?", "질문 기록은 어디서 봐요?", "답변이 이상할 때는?"]
SUPPORT_FAQ = [
    ("문서 업로드 방법", "문서는 어떻게 올려요?"),
    ("모델을 고르지 않으면 어떻게 돼요?", "모델을 고르지 않으면 어떻게 돼요?"),
    ("질문 기록은 어디서 봐요?", "질문 기록은 어디서 봐요?"),
    ("안전 요건 안내 문구의 뜻", "안전 요건 안내 문구는 무슨 뜻이에요?"),
]
ADMIN_NAME = "김안전"
