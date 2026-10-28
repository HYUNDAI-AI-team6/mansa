import logging
import unittest
from dataclasses import dataclass, field

from features.processing.indexer import Indexer
from features.processing.pipeline import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PROCESSING,
    AlreadyProcessingError,
    IngestError,
    IngestPipeline,
    IngestSteps,
)


def setUpModule():
    """실패 시나리오가 남기는 오류 로그로 테스트 출력이 어지러워지지 않게 로그를 끈다."""
    logging.disable(logging.CRITICAL)


def tearDownModule():
    """다른 테스트에 영향이 없도록 로그를 다시 켠다."""
    logging.disable(logging.NOTSET)


@dataclass
class FakeDocument:
    id: int = 1
    doc_type: str = "tech"
    file_path: str = "/files/a.pdf"


@dataclass
class FakeChunk:
    text: str
    metadata: dict = field(default_factory=dict)


class FakeDocuments:
    """상태 변경을 기록하는 DocumentService 대역."""

    def __init__(self, document=None, fail_on_status=None):
        self.document = document or FakeDocument()
        self.fail_on_status = fail_on_status
        self.statuses = []

    def get_document(self, document_id):
        return self.document

    def set_status(self, document_id, status, error=None):
        if status == self.fail_on_status:
            raise RuntimeError("db down")
        self.statuses.append((status, error))


class FakeStore:
    """ChromaDB 대역. 저장·삭제를 문서 ID별 청크 수로 기록한다."""

    def __init__(self):
        self.stored = {}
        self.deleted = []

    def upload(self, doc_type, collection, ids, vectors, texts, metadatas):
        for meta in metadatas:
            self.stored[meta["document_id"]] = self.stored.get(meta["document_id"], 0) + 1
        return len(ids)

    def count(self, doc_type, document_id):
        return self.stored.get(document_id, 0)

    def delete(self, doc_type, document_id):
        self.deleted.append(document_id)
        self.stored.pop(document_id, None)

    def indexer(self):
        return Indexer(upload=self.upload, count_stored=self.count, delete_document=self.delete)


def make_chunks(count, document_id=1):
    return [
        FakeChunk(f"본문{i}", {"source": "a.pdf", "page": 1, "chunk": i,
                              "document_id": document_id, "document_type": "tech"})
        for i in range(count)
    ]


def make_steps(**overrides):
    base = dict(
        extract=lambda path: "content",
        chunk=lambda document, content: make_chunks(5),
        tag=lambda chunks: chunks,
        embed=lambda texts: [[0.1, 0.2] for _ in texts],
    )
    base.update(overrides)
    return IngestSteps(**base)


class IngestPipelineTest(unittest.TestCase):
    def setUp(self):
        self.documents = FakeDocuments()
        self.store = FakeStore()

    def pipeline(self, **step_overrides):
        return IngestPipeline(self.documents, make_steps(**step_overrides), self.store.indexer(), batch_size=2)

    def test_success_embeds_in_batches_and_completes(self):
        batches = []
        pipeline = self.pipeline(embed=lambda texts: batches.append(len(texts)) or [[0.1, 0.2]] * len(texts))
        pipeline.run(1)
        self.assertEqual(batches, [2, 2, 1])
        self.assertEqual(self.store.stored, {1: 5})
        self.assertEqual([s for s, _ in self.documents.statuses], [STATUS_PROCESSING, STATUS_COMPLETED])

    def test_extraction_error_is_recorded_with_its_message_and_stops_early(self):
        def extract(path):
            raise IngestError("스캔 PDF는 지원하지 않아요")

        embedded = []
        self.pipeline(extract=extract, embed=lambda t: embedded.append(t)).run(1)
        self.assertEqual(self.documents.statuses[-1], (STATUS_FAILED, "스캔 PDF는 지원하지 않아요"))
        self.assertEqual(embedded, [])
        self.assertEqual(self.store.stored, {})

    def test_unexpected_extraction_error_hides_its_message(self):
        def extract(path):
            raise OSError("/secret/path/a.pdf")

        self.pipeline(extract=extract).run(1)
        status, error = self.documents.statuses[-1]
        self.assertEqual(status, STATUS_FAILED)
        self.assertNotIn("/secret", error)
        self.assertIn("OSError", error)

    def test_chunker_receives_the_document_and_extracted_content(self):
        seen = []

        def chunk(document, content):
            seen.append((document.file_path, content))
            return make_chunks(1)

        self.pipeline(extract=lambda path: ("content of", path), chunk=chunk).run(1)
        self.assertEqual(seen, [("/files/a.pdf", ("content of", "/files/a.pdf"))])

    def test_no_chunks_fails(self):
        self.pipeline(chunk=lambda d, c: []).run(1)
        self.assertEqual(self.documents.statuses[-1][0], STATUS_FAILED)

    def test_bad_metadata_fails_before_embedding(self):
        embedded = []
        bad = lambda d, c: [FakeChunk("본문", {"source": "a.pdf"})]
        self.pipeline(chunk=bad, embed=lambda t: embedded.append(t)).run(1)
        self.assertEqual(self.documents.statuses[-1][0], STATUS_FAILED)
        self.assertEqual(embedded, [])

    def test_embedding_failure_cleans_up_and_hides_message(self):
        calls = []

        def embed(texts):
            calls.append(len(texts))
            if len(calls) == 2:
                raise RuntimeError("Incorrect API key provided: sk-secret")
            return [[0.1, 0.2]] * len(texts)

        self.pipeline(embed=embed).run(1)
        status, error = self.documents.statuses[-1]
        self.assertEqual(status, STATUS_FAILED)
        self.assertNotIn("sk-secret", error)
        self.assertIn("RuntimeError", error)
        self.assertEqual(self.store.deleted, [1])
        self.assertEqual(self.store.stored, {})

    def test_count_mismatch_fails_and_cleans_up(self):
        self.store.count = lambda doc_type, document_id: 0
        self.pipeline().run(1)
        self.assertEqual(self.documents.statuses[-1][0], STATUS_FAILED)
        self.assertEqual(self.store.deleted, [1])

    def test_tagging_failure_does_not_stop_processing(self):
        def tag(chunks):
            raise RuntimeError("tag api down")

        self.pipeline(tag=tag).run(1)
        self.assertEqual(self.documents.statuses[-1][0], STATUS_COMPLETED)
        self.assertEqual(self.store.stored, {1: 5})

    def test_rejects_concurrent_run_of_the_same_document(self):
        pipeline = None

        def embed(texts):
            with self.assertRaises(AlreadyProcessingError):
                pipeline.run(1)
            return [[0.1, 0.2]] * len(texts)

        pipeline = self.pipeline(embed=embed)
        pipeline.run(1)
        self.assertEqual(self.documents.statuses[-1][0], STATUS_COMPLETED)

    def test_guard_is_released_after_failure(self):
        pipeline = self.pipeline(chunk=lambda d, c: [])
        pipeline.run(1)
        pipeline.run(1)
        self.assertEqual([s for s, _ in self.documents.statuses].count(STATUS_FAILED), 2)

    def test_run_does_not_raise_when_failure_cannot_be_recorded(self):
        self.documents.fail_on_status = STATUS_FAILED
        self.pipeline(chunk=lambda d, c: []).run(1)
        self.assertEqual([s for s, _ in self.documents.statuses], [STATUS_PROCESSING])


if __name__ == "__main__":
    unittest.main()
