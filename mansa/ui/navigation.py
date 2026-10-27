"""메뉴와 화면 목록 (Figma 화면 확정안 2026-10-26 기준).

Figma 머리글에는 설명 문구가 없어서 description 은 비워 둔다(필요하면 넣을 수 있음).
"""

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
    Page("history", "질문 기록", "clock", "user"),
    Page("doc_view", "문서 조회", "file", "user"),
    Page("support", "고객센터", "headset", "user"),
    # 관리자 메뉴 (파란 메뉴바)
    Page("documents", "문서 관리", "folder", "admin"),
    Page("upload", "문서 업로드", "file-up", "admin"),
    Page("master", "기준정보", "database", "admin"),
    Page("evaluation", "평가", "chart", "admin"),
    Page("question_test", "질문 테스트", "flask", "admin"),
    Page("members", "회원 관리", "users", "admin"),
]

PAGE_BY_KEY = {p.key: p for p in PAGES}
HOME = {"user": "qa", "admin": "documents"}


def pages_for(role: str) -> list[Page]:
    """권한에 맞는 메뉴 목록을 돌려준다."""
    return [p for p in PAGES if p.role == role]
