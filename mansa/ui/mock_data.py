"""화면 확인용 목데이터.

features/ 기능이 붙기 전까지 화면이 이 값을 사용한다.
각 함수의 docstring에 나중에 바꿔 끼울 기능 함수 자리를 적어 둔다.
"""

from dataclasses import dataclass, field

MODELS = ["[모델 A]", "[모델 B]", "[모델 C]"]
DEPARTMENTS = ["유지보수팀", "안전팀", "검사·품질팀"]

# ---------------------------------------------------------------- 로그인
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
