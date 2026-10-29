"""ChromaDB 대신 쓰는 메모리 저장소. Indexer 생성자에 끼워 넣어 쓴다."""

from features.processing.indexer import Indexer


class FakeChroma:
    """(문서 유형, 문서 ID)별로 저장된 청크를 메모리에 두고 Indexer의 세 외부 호출에 답한다."""

    def __init__(self) -> None:
        self.stored: dict[str, dict] = {}
        self.uploads = 0

    def upload(self, doc_type, collection, ids, vectors, texts, metadatas) -> int:
        """같은 id는 덮어쓴다. 저장한 개수를 돌려준다."""
        self.uploads += 1
        for id_, vector, text, meta in zip(ids, vectors, texts, metadatas, strict=True):
            self.stored[id_] = {"doc_type": doc_type, "collection": collection, "vector": vector, "text": text, "meta": meta}
        return len(ids)

    def count_stored(self, doc_type: str, document_id: int) -> int:
        """문서 ID가 같은 청크 수를 센다."""
        return len(self.chunks_of(doc_type, document_id))

    def delete_document(self, doc_type: str, document_id: int) -> None:
        """문서 ID가 같은 청크를 모두 지운다."""
        for id_ in list(self.chunks_of(doc_type, document_id)):
            del self.stored[id_]

    def chunks_of(self, doc_type: str, document_id: int) -> dict[str, dict]:
        """문서 ID가 같은 청크를 id별로 돌려준다."""
        return {
            id_: item
            for id_, item in self.stored.items()
            if item["doc_type"] == doc_type and item["meta"]["document_id"] == document_id
        }

    def indexer(self) -> Indexer:
        """이 저장소를 쓰는 Indexer를 만든다."""
        return Indexer(self.upload, self.count_stored, self.delete_document)
