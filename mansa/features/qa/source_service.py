"""근거 원문 조회(명세서 SourceService). 답변의 근거 청크 ID로 원문 창에 보여 줄 내용을 만든다."""

from typing import Any
from core.schemas import SourceView


class SourceService:
    """메모리에 읽어 둔 청크라서 근거 원문을 찾는다. Chroma를 다시 부르지 않는다.
    
    chunks는 load_corpus가 읽은 {"id", "text", "metadata"} 목록이며, 메뉴얼·안전 문서를 합쳐 넘긴다.
    shortcut: 앱을 켤 때 읽은 청크만 찾는다, 이후 올라온 문서도 보여야 하면 Chroma에서 직접 읽도록 바꾼다.
    """

    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        """청크를 ID와 (문서, 페이지, 청크 번호)로 찾을 수 있게 정리해 둔다."""
        self._by_id = {chunk["id"]: chunk for chunk in chunks}
        self._by_position = {_position(chunk.get("metadata", {})): chunk["text"] for chunk in chunks}

    def get_source(self, chunk_id: str) -> SourceView:
        """근거 청크의 원문·같은 페이지 앞뒤 청크·문서명·페이지를 반환한다.
        
        문서명은 메타데이터의 doc_name, 없으면 파일 이름(source)이다. 앞뒤 청크가 없으면 빈 문자열이다.
        없는 청크 ID면 LookupError를 발생시킨다.
        """
        chunk = self._by_id.get(chunk_id)
        if chunk is None:
            raise LookupError(f"source chunk not found: {chunk_id}")
        meta = chunk.get("metadata", {})
        source, page, number = _position(meta)
        return SourceView(
            chunk_id=chunk_id,
            text=chunk["text"],
            before=self._by_position.get((source, page, number - 1), ""),
            after=self._by_position.get((source, page, number + 1), ""),
            doc_name=meta.get("doc_name") or source,
            page=page,
            department=meta.get("department", ""),
            clause=meta.get("clause", ""),
        )


def _position(meta: dict[str, Any]) -> tuple[str, int | None, int]:
    """청크의 (문서 파일, 페이지, 페이지 안 청크 번호). 앞뒤 문단을 찾는 열쇠로 쓴다."""
    return meta.get("source", ""), meta.get("page"), meta.get("chunk", 0)