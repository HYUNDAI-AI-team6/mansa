from dataclasses import dataclass
from pathlib import Path

import pymupdf

# 페이지에 이 글자 수 이상이 있어야 텍스트 페이지로 본다.
MIN_TEXT_CHARS = 50
# 텍스트 페이지 비율이 이 값 미만이면 스캔 PDF로 보고 지원하지 않는다.
MIN_TEXT_PAGE_RATIO = 0.3


class PdfExtractionError(Exception):
    """PDF를 열거나 추출할 수 없을 때의 공통 예외."""


class ScannedPdfError(PdfExtractionError):
    """텍스트가 거의 없는 스캔 PDF라서 지원하지 않을 때의 예외."""


@dataclass(frozen=True)
class PageText:
    """한 페이지의 텍스트 추출 결과. page_no는 1부터 시작한다."""

    page_no: int
    text: str
    char_count: int
    image_count: int
    is_low_text: bool


@dataclass(frozen=True)
class PdfText:
    """PDF 한 개의 페이지별 텍스트 추출 결과."""

    file_name: str
    page_count: int
    pages: list[PageText]

    @property
    def low_text_pages(self) -> list[int]:
        """텍스트가 거의 없는 페이지 번호 목록을 반환한다. 이미지·도면 위주 페이지일 수 있다."""
        return [p.page_no for p in self.pages if p.is_low_text]


def is_scanned(pages: list[PageText]) -> bool:
    """텍스트 페이지 비율이 MIN_TEXT_PAGE_RATIO 미만이면 True. 페이지가 없으면 True."""
    if not pages:
        return True
    text_pages = sum(1 for p in pages if not p.is_low_text)
    return text_pages / len(pages) < MIN_TEXT_PAGE_RATIO


def extract_pdf_text(path: str | Path) -> PdfText:
    """PDF에서 페이지별 텍스트를 추출한다. OCR은 하지 않는다.

    파일이 없거나 PDF가 아니거나 암호화·손상된 경우 PdfExtractionError를,
    텍스트 페이지 비율이 낮은 스캔 PDF는 ScannedPdfError를 발생시킨다.
    페이지 텍스트는 PyMuPDF가 준 원문 그대로이며 공백·줄바꿈을 정리하지 않는다.
    표 추출은 하지 않으므로 표 안의 글자도 본문 텍스트에 그대로 들어 있다.
    """
    path = Path(path)
    if not path.is_file():
        raise PdfExtractionError(f"file not found: {path.name}")
    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise PdfExtractionError(f"cannot open pdf: {path.name}") from exc

    with doc:
        if doc.needs_pass:
            raise PdfExtractionError(f"encrypted pdf is not supported: {path.name}")
        pages = []
        for page in doc:
            text = page.get_text()
            char_count = len(text.strip())
            pages.append(
                PageText(
                    page_no=page.number + 1,
                    text=text,
                    char_count=char_count,
                    image_count=len(page.get_images()),
                    is_low_text=char_count < MIN_TEXT_CHARS,
                )
            )

    if is_scanned(pages):
        raise ScannedPdfError(f"scanned pdf is not supported: {path.name}")
    return PdfText(file_name=path.name, page_count=len(pages), pages=pages)
