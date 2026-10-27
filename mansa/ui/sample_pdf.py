"""시연용 샘플 PDF 만들기 (목데이터에는 진짜 PDF 파일이 없어서 그때그때 만든다).

외부 라이브러리 없이 PDF 를 직접 쓴다. 한글은 글꼴을 PDF 안에 넣지 않고 Adobe-Korea1 문자 모음
(HYGoThic-Medium)으로 적어 두면 PDF 뷰어가 컴퓨터에 있는 한글 글꼴로 보여 준다.
실제 문서 저장소가 연결되면 이 파일 대신 등록된 원본 PDF 를 열도록 바꾼다.
"""

import base64

PAGE_W, PAGE_H = 595, 842  # A4 (pt)
MARGIN = 56


def _hex(text: str) -> str:
    """글자를 UTF-16BE 16진수 문자열로 바꾼다(PDF 의 UCS2 글꼴 인코딩용)."""
    return text.encode("utf-16-be").hex().upper()


def _content(title: str, lines: list[str]) -> bytes:
    """페이지 그림 명령: 큰 제목 한 줄 + 설명 여러 줄."""
    y = PAGE_H - MARGIN - 24
    ops = [f"BT /F1 24 Tf {MARGIN} {y} Td <{_hex(title)}> Tj ET"]
    y -= 44
    for line in lines:
        if line:
            ops.append(f"BT /F1 12 Tf 0.35 0.38 0.44 rg {MARGIN} {y} Td <{_hex(line)}> Tj ET")
        y -= 24
    return "\n".join(ops).encode("ascii")


def sample_pdf(title: str, lines: list[str]) -> bytes:
    """제목과 설명 줄로 한 장짜리 샘플 PDF 바이트를 만든다."""
    stream = _content(title, lines)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
            "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ).encode("ascii"),
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        (
            b"<< /Type /Font /Subtype /Type0 /BaseFont /HYGoThic-Medium "
            b"/Encoding /UniKS-UCS2-H /DescendantFonts [6 0 R] >>"
        ),
        (
            b"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /HYGoThic-Medium "
            b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Korea1) /Supplement 1 >> "
            b"/DW 1000 /W [1 95 500] >>"
        ),
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_at,
    )
    return bytes(out)


def doc_pdf_base64(doc: dict) -> str:
    """문서 한 건의 샘플 PDF 를 base64 글자로 돌려준다(브라우저에서 바로 열 수 있게)."""
    lines = [
        f"유형: {doc['type']}",
        f"부서: {doc['dept']}",
        f"등록일: {doc['date']}",
        "",
        "이 파일은 시연용 샘플이에요.",
        "실제 서비스에서는 등록된 원본 PDF 가 열려요.",
    ]
    return base64.b64encode(sample_pdf(doc["title"], lines)).decode("ascii")
