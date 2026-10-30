"""문서 관리(A1): documents_info 테이블의 문서 현황 + 목록(처리 상태: 처리 중 · 완료 · 실패).

삭제는 검색 데이터(ChromaDB 청크) → 원본 PDF → 문서 기록 순서로 지운다(features.processing.workflow).
"""

import logging
from html import escape

import gradio as gr

from ui import components as ui
from ui.doc_view import title_label
from ui.page import PageView
from ui.theme import TEXT3

logger = logging.getLogger(__name__)

COLUMNS = [
    ("문서", "1fr"),
    ("유형", "116px"),
    ("부서", "128px"),
    ("처리 상태", "128px"),
    ("등록일", "64px"),
    ("", "48px"),
]
# 현황 카드: (이름, 설명, 아이콘, 색)
STATS = [
    ("기술 문서", "매뉴얼 · 사양서", "file", "blue"),
    ("안전 문서", "법규 · 지침 · 사내 규정", "shield", "orange"),
    ("처리 중", "추출 · 청킹 · 색인 진행", "refresh", "blue"),
    ("실패", "다시 올려 주세요", "alert", "red"),
]
ICON_COLOR = {"blue": "#2F54EB", "orange": "#C2410C", "red": "#B91C1C"}

# documents_info 값 -> 화면에 보이는 이름
TYPE_LABEL = {"tech": "기술 문서", "secure": "안전 문서"}
STATUS_LABEL = {"PROCESSING": "처리 중", "COMPLETED": "완료", "FAILED": "실패"}

REFRESH_SECONDS = 5  # 처리 상태를 다시 읽는 간격

SELECT_DOCS = (
    "SELECT d.id, d.filename, d.document_type, d.status, d.upload_at, p.name AS dept "
    "FROM documents_info d LEFT JOIN departments p ON p.id = d.department_id "
    "ORDER BY d.upload_at DESC, d.id DESC"
)


def load_docs() -> list[dict]:
    """documents_info 를 부서명과 함께 읽어 화면용 dict 목록으로 만든다. DB 연결이 필요해 호출할 때 불러온다."""
    from util.mysql_connection import fetch_all

    return [
        {
            "id": r["id"],
            "title": r["filename"],
            "type": TYPE_LABEL[r["document_type"]],
            "dept": r["dept"] or "-",
            "status": STATUS_LABEL[r["status"]],
            "date": r["upload_at"].strftime("%m/%d"),
        }
        for r in fetch_all(SELECT_DOCS)
    ]


def stats_html(docs: list[dict]) -> str:
    """현황 카드 4개."""
    cards = []
    for name, desc, icon, color in STATS:
        key = "type" if name.endswith("문서") else "status"
        count = sum(d[key] == name for d in docs)
        cards.append(
            f'<div class="card stat"><span class="tile {color}">'
            f"{ui.icon(icon, ICON_COLOR[color], 20)}</span>"
            f'<div><span class="label">{escape(name)}</span><b>{count}</b>'
            f'<span class="desc">{escape(desc)}</span></div></div>'
        )
    return f'<div class="stats">{"".join(cards)}</div>'


FAILED_HINT = "삭제한 뒤 다시 올려 주세요"


def _title(doc: dict) -> str:
    """문서 이름. 실패한 문서는 같은 이름으로 다시 올릴 수 없어서(같은 이름·유형은 한 건만 등록) 안내를 덧붙인다."""
    label = title_label(doc)
    return f"{label}<em>{FAILED_HINT}</em>" if doc["status"] == "실패" else label


def table(docs: list[dict], keyword: str = "") -> str:
    """문서 표. 휴지통 버튼의 data-i 는 documents_info 의 id 다."""
    word = (keyword or "").strip()
    rows = []
    for d in docs:
        if word not in d["title"]:
            continue
        trash = (
            f'<button type="button" class="icon-btn" data-i="{d["id"]}" '
            f'aria-label="{escape(d["title"])} 삭제">{ui.icon("trash", TEXT3, 18)}</button>'
        )
        rows.append(
            [
                ui.cell(_title(d)),
                ui.cell(ui.tag(d["type"], ui.TYPE_TAG[d["type"]])),
                ui.cell(ui.dept_tag(d["dept"])),
                ui.cell(ui.tag(d["status"], ui.STATUS_TAG[d["status"]])),
                ui.cell(f"<em>{escape(d['date'])}</em>"),
                ui.cell(trash),
            ]
        )
    return ui.table_html(COLUMNS, rows, "조건에 맞는 문서가 없어요")


def _busy(docs: list[dict]) -> bool:
    """처리 중인 문서가 하나라도 있으면 True."""
    return any(d["status"] == "처리 중" for d in docs)


def _delete(keyword: str, evt: gr.SelectData) -> tuple:
    """휴지통을 누른 문서를 지우고 목록을 다시 그린다. evt.index 는 documents_info 의 id 다.

    검색 데이터 → 원본 PDF → 문서 기록 순서로 지운다. 이 프로세스에서 처리 중인 문서는 지우지 않는다.
    지우지 못하면 이유를 알리고, 문서 기록이 남아 있어 목록에서 다시 지울 수 있다.
    """
    from features.documents.errors import DocumentNotFoundError
    from features.processing.deletion import DeletionError
    from features.processing.workflow import default_workflow

    try:
        result = default_workflow().delete(int(evt.index))
        # 다른 컴퓨터에서 올렸거나 앞선 시도에서 이미 지워진 경우 원본 파일이 없을 수 있다.
        ui.notify("문서를 삭제했어요" if result.pdf_existed else "문서를 삭제했어요. 원본 파일은 이미 없었어요")
    except DocumentNotFoundError:
        ui.notify("이미 삭제된 문서예요")
    except DeletionError as exc:  # 처리 중·단계별 실패. 메시지는 사용자에게 보여도 되는 문구다.
        ui.warn(str(exc))
    except Exception:
        logger.exception("delete failed: document_id=%s", evt.index)
        ui.warn("문서를 삭제하지 못했어요. 잠시 후 다시 시도해 주세요")
    docs = load_docs()
    return stats_html(docs), table(docs, keyword)


def build() -> PageView:
    """문서 관리 화면을 만든다. '문서 업로드' 버튼은 app.py 에서 업로드 화면으로 연결한다."""
    with gr.Row(elem_classes=["section-row"]):
        gr.HTML(ui.section_title("현황"), padding=False, scale=1)
        upload = gr.Button(
            "문서 업로드", elem_classes=["btn-primary", "sm-btn"], scale=0, min_width=0
        )
    stats = gr.HTML(stats_html([]), padding=False)
    with gr.Column(elem_classes=["card"]):
        keyword = ui.search_box("문서명 검색", ["w-280"])
        result = gr.HTML(table([]), js_on_load=ui.CLICK_JS, padding=False)

    keyword.change(lambda k: table(load_docs(), k), keyword, result)
    result.select(_delete, keyword, [stats, result])

    # 처리 중인 문서가 있을 때만 켜 두고, 다른 화면으로 가면 app.py 가 끈다.
    timer = gr.Timer(REFRESH_SECONDS, active=False)

    def refresh(word: str) -> tuple:
        """DB 의 지금 상태로 현황·표를 다시 그린다. 처리 중인 문서가 없으면 타이머를 끈다."""
        docs = load_docs()
        return stats_html(docs), table(docs, word), gr.Timer(active=_busy(docs))

    timer.tick(refresh, keyword, [stats, result, timer])

    def reset() -> tuple:
        """메뉴로 들어오면 검색어를 비우고 DB 의 지금 문서 목록으로 다시 그린다."""
        docs = load_docs()
        return "", stats_html(docs), table(docs), gr.Timer(active=_busy(docs))

    return PageView(
        reset, [], [keyword, stats, result, timer], links={"upload": upload, "timer": timer}
    )
