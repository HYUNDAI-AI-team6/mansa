"""PyMuPDF 추출 가능 여부 진단 스크립트 (Step 2).

재사용할 추출 모듈이 아니라 data/pdfs/ 의 실제 PDF를 분석해 통계만 출력한다.
unittest 탐색 대상이 아니도록 test_ 접두사를 쓰지 않았다.

실행: uv run python tests/diagnose_pdf_extraction.py [--sample-pages 1 5 ...]
"""

import re
import sys
import time
from pathlib import Path

import pymupdf

PDF_DIR = Path(__file__).resolve().parents[2] / "data" / "pdfs"
LOW_TEXT_CHARS = 50
HANGUL = re.compile(r"[가-힣]")
LATIN = re.compile(r"[A-Za-z]")
CLAUSE = re.compile(r"^\s*(\d+(?:\.\d+)+)\s+\S", re.MULTILINE)
MODEL_KEYWORDS = ["LUXEN", "NEW YZER", "YZER", "엘트론", "ELTRON"]
BROKEN_MARKERS = ["�", "(cid:"]


def analyze(path: Path) -> dict:
    doc = pymupdf.open(path)
    pages = []
    for page in doc:
        text = page.get_text()
        started = time.perf_counter()
        tables = page.find_tables().tables
        find_sec = time.perf_counter() - started
        table_info = []
        for t in tables:
            rows = t.extract()
            cells = [c for r in rows for c in r]
            empty = sum(1 for c in cells if not (c or "").strip())
            table_info.append(
                {
                    "rows": len(rows),
                    "cols": t.col_count,
                    "empty_ratio": empty / len(cells) if cells else 1.0,
                }
            )
        pages.append(
            {
                "no": page.number + 1,
                "chars": len(text.strip()),
                "hangul": len(HANGUL.findall(text)),
                "latin": len(LATIN.findall(text)),
                "images": len(page.get_images()),
                "broken": sum(text.count(m) for m in BROKEN_MARKERS),
                "clauses": CLAUSE.findall(text),
                "tables": table_info,
                "find_sec": find_sec,
                "text": text,
            }
        )
    return {"name": path.name, "pages": pages}


def report(result: dict, sample_pages: list[int]) -> None:
    pages = result["pages"]
    n = len(pages)
    with_text = [p for p in pages if p["chars"] >= LOW_TEXT_CHARS]
    low = [p["no"] for p in pages if p["chars"] < LOW_TEXT_CHARS]
    table_pages = [p for p in pages if p["tables"]]
    all_tables = [t for p in pages for t in p["tables"]]
    full_text = "\n".join(p["text"] for p in pages)

    print("=" * 70)
    print(result["name"])
    print(f"pages={n} text_pages(>={LOW_TEXT_CHARS} chars)={len(with_text)} low_text_pages={low}")
    print(
        f"chars: total={sum(p['chars'] for p in pages)} "
        f"min={min(p['chars'] for p in pages)} max={max(p['chars'] for p in pages)}"
    )
    print(
        f"hangul={sum(p['hangul'] for p in pages)} latin={sum(p['latin'] for p in pages)} "
        f"broken_markers={sum(p['broken'] for p in pages)} "
        f"pages_with_images={sum(1 for p in pages if p['images'])}"
    )
    print("model keyword counts:", {k: full_text.count(k) for k in MODEL_KEYWORDS})
    clauses = [c for p in pages for c in p["clauses"]]
    pages_with_clause = sum(1 for p in pages if p["clauses"])
    print(f"clause-like numbers: total={len(clauses)} pages={pages_with_clause} first10={clauses[:10]}")
    print(
        f"tables: total={len(all_tables)} pages_with_tables={len(table_pages)}/{n} "
        f"find_tables_time={sum(p['find_sec'] for p in pages):.1f}s"
    )
    if all_tables:
        sparse = [t for t in all_tables if t["empty_ratio"] > 0.5]
        tiny = [t for t in all_tables if t["rows"] < 2 or t["cols"] < 2]
        print(
            f"  avg_rows={sum(t['rows'] for t in all_tables) / len(all_tables):.1f} "
            f"avg_cols={sum(t['cols'] for t in all_tables) / len(all_tables):.1f} "
            f"sparse(>50% empty)={len(sparse)} tiny(<2 rows or cols)={len(tiny)}"
        )
    print("  pages_with_tables:", [(p["no"], len(p["tables"])) for p in table_pages][:40])
    # 표가 있는데 본문 텍스트가 많은 페이지 / 텍스트가 많은데 표가 없는 페이지 후보
    no_table_text_heavy = [p["no"] for p in pages if not p["tables"] and p["chars"] > 1500]
    print(f"  text-heavy pages without tables (>1500 chars): {len(no_table_text_heavy)}")

    for no in sample_pages:
        if not 1 <= no <= n:
            continue
        p = pages[no - 1]
        snippet = re.sub(r"\s+", " ", p["text"]).strip()[:300]
        print(f"-- sample page {no}: chars={p['chars']} tables={len(p['tables'])}")
        print(f"   text: {snippet}")
        if p["tables"]:
            print(f"   first table: {p['tables'][0]}")


def main() -> None:
    args = sys.argv[1:]
    samples_override = None
    if args and args[0] == "--sample-pages":
        samples_override = [int(a) for a in args[1:]]
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"PDF 없음: {PDF_DIR}")
        sys.exit(1)
    for pdf in pdfs:
        report(analyze(pdf), samples_override or [1, 3, 5])


if __name__ == "__main__":
    main()
