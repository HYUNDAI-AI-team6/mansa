"""메뉴와 화면 목록 (Figma 화면 확정안 2026-10-26 기준)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Page:
    """메뉴 하나와 그 화면의 머리글 정보."""

    key: str
    label: str
    icon: str
    role: str  # "user" | "admin"
    description: str | None = None


PAGES: list[Page] = [
    # 사용자 메뉴 (흰 메뉴바)
    Page("qa", "기술 Q&A", "chat", "user"),
    Page(
        "history",
        "질문 기록",
        "clock",
        "user",
        "지난 기술 Q&A 대화 목록이에요. 제목은 첫 질문을 바탕으로 자동으로 만들어져요.",
    ),
    Page("doc_view", "문서 조회", "file", "user", "등록된 매뉴얼·안전 문서를 찾아봐요"),
    Page(
        "support",
        "고객센터",
        "headset",
        "user",
        "MANSA 사용법을 안내하고, 필요하면 관리자와 연결해 드려요",
    ),
    # 관리자 메뉴 (파란 메뉴바)
    Page(
        "documents",
        "문서 관리",
        "folder",
        "admin",
        "문서를 올리면 추출 → 청킹 → 색인까지 자동으로 처리돼요",
    ),
    Page("upload", "문서 업로드", "file-up", "admin", "필수값을 넣고 올리면 자동으로 처리돼요"),
    Page("master", "기준정보", "database", "admin", "부서 · 설비 모델 · 작업 분류표를 확인해요"),
    Page(
        "evaluation",
        "평가",
        "chart",
        "admin",
        "테스트셋으로 기술 Q&A와 고객센터 답변 품질을 확인해요",
    ),
    Page("question_test", "질문 테스트", "flask", "admin"),
    Page(
        "members", "회원 관리", "users", "admin", "관리자가 계정을 만들고 권한·부서·상태를 관리해요"
    ),
]

PAGE_BY_KEY = {p.key: p for p in PAGES}
HOME = {"user": "qa", "admin": "documents"}


def pages_for(role: str) -> list[Page]:
    """권한에 맞는 메뉴 목록을 돌려준다."""
    return [p for p in PAGES if p.role == role]
