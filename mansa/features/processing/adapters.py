"""파이프라인 단계 함수를 실제 구현에 연결하는 어댑터.

pipeline.py는 PDF 라이브러리를 몰라도 되도록 단계 함수를 주입받는다. 이 모듈이 추출 함수의
예외를 문서 상태에 남겨도 되는 문구(IngestError)로 바꿔 준다.
"""

from collections.abc import Callable
from typing import Any

from features.processing.pdf_content import PdfContent, extract_pdf_content
from features.processing.pdf_text import PdfExtractionError, ScannedPdfError
from features.processing.pipeline import IngestError


def extract_content(
    path: str, extractor: Callable[[str], Any] = extract_pdf_content
) -> PdfContent:
    """PDF에서 본문·표를 추출하고, 추출 오류는 사용자용 문구의 IngestError로 바꿔 던진다.

    스캔 PDF와 열 수 없는 PDF(없는 파일·손상·암호화)를 구분해서 알린다.
    ScannedPdfError가 PdfExtractionError의 하위 예외라서 스캔본을 먼저 잡는다.
    그 밖의 예외는 바꾸지 않는다. 파이프라인이 예외 이름만 상태에 남기고 로그에 자세히 기록한다.
    """
    try:
        return extractor(path)
    except ScannedPdfError as exc:
        raise IngestError("스캔 PDF는 지원하지 않아요") from exc
    except PdfExtractionError as exc:
        raise IngestError("PDF를 열 수 없어요") from exc
