import re
import unittest
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from features.processing.adapters import extract_content
from features.processing.chunker import chunk
from features.processing.indexer import Indexer
from features.processing.pdf_content import PageContent, PdfContent
from features.processing.pipeline import IngestPipeline, IngestSteps

PDF_DIR = Path(__file__).resolve().parents[2] / "data" / "pdfs"
SAFETY_PDF = PDF_DIR / "안전기준.pdf"
ELTRON_PDF = PDF_DIR / "엘트론엘리베이터_기술사양서.pdf"
LUXEN_PDF = PDF_DIR / "Passenger Elevator_LUXEN NEW YZER_2406.pdf"


@dataclass
class FakeDocument:
    doc_type: str
    id: int = 5
    title: str = "문서"
    filename: str = "문서.pdf"


def make_content(*bodies: str) -> PdfContent:
    """본문만 있는 페이지들로 PdfContent를 만든다."""
    pages = [
        PageContent(page_no=i, body_text=body, tables=[], is_low_text=False, image_count=0)
        for i, body in enumerate(bodies, start=1)
    ]
    return PdfContent(file_name="a.pdf", page_count=len(pages), pages=pages, failed_table_pages=[])


SECURE_BODY = "6.5 승강로\n6.5.1 일반사항\n6.5.1.1 승강로에는 1대 이상의 엘리베이터 카가 있을 수 있다."
TECH_BODY = "ELVRO 3000 방폭형 화물용 엘리베이터에 관한 설명이 이어지는 문장이다. 사양은 아래와 같다."


class DispatchTest(unittest.TestCase):
    def test_secure_document_is_split_by_clause(self) -> None:
        chunks = chunk(FakeDocument("secure"), make_content(SECURE_BODY))

        self.assertEqual(chunks[0].metadata["clause"], "6.5")
        self.assertEqual(chunks[0].metadata["document_type"], "secure")

    def test_tech_document_uses_models(self) -> None:
        chunks = chunk(FakeDocument("tech"), make_content(TECH_BODY), ["ELVRO 3000"])

        self.assertEqual(chunks[0].metadata["model"], "ELVRO 3000")
        self.assertEqual(chunks[0].metadata["document_type"], "tech")

    def test_tech_document_without_models_has_no_model(self) -> None:
        chunks = chunk(FakeDocument("tech"), make_content(TECH_BODY))

        self.assertNotIn("model", chunks[0].metadata)

    def test_secure_document_ignores_models(self) -> None:
        with_models = chunk(FakeDocument("secure"), make_content(SECURE_BODY), ["ELVRO 3000"])
        without = chunk(FakeDocument("secure"), make_content(SECURE_BODY))

        self.assertEqual([c.text for c in with_models], [c.text for c in without])
        self.assertTrue(all("model" not in c.metadata for c in with_models))

    def test_unknown_doc_type_raises_before_chunking(self) -> None:
        with self.assertRaises(ValueError):
            chunk(FakeDocument("SPEC"), make_content(SECURE_BODY))

    def test_partial_matches_the_pipeline_step_signature(self) -> None:
        step = partial(chunk, models=["ELVRO 3000"])

        chunks = step(FakeDocument("tech"), make_content(TECH_BODY))

        self.assertEqual(chunks[0].metadata["model"], "ELVRO 3000")

    def test_can_be_used_as_ingest_step(self) -> None:
        steps = IngestSteps(
            extract=lambda path: make_content(TECH_BODY),
            chunk=partial(chunk, models=["ELVRO 3000"]),
            tag=lambda chunks: chunks,
            embed=lambda texts: [[0.0] for _ in texts],
        )

        chunks = steps.chunk(FakeDocument("tech"), steps.extract("a.pdf"))

        self.assertEqual(len(chunks), 1)


class FakeStore:
    """ChromaDB와 문서 서비스를 대신하는 메모리 저장소. 외부 서버와 API를 호출하지 않는다."""

    def __init__(self, document: "PipelineDocument") -> None:
        self.document = document
        self.stored: dict[str, dict] = {}
        self.statuses: list[tuple] = []

    def get_document(self, document_id: int) -> "PipelineDocument":
        return self.document

    def set_status(self, document_id: int, status: str, error: str | None = None, chunk_count: int | None = None) -> None:
        self.statuses.append((status, error, chunk_count))

    def upload(self, doc_type, collection, ids, vectors, texts, metadatas) -> int:
        for id_, vector, text, meta in zip(ids, vectors, texts, metadatas):
            self.stored[id_] = {"vector": vector, "text": text, "meta": meta, "collection": collection}
        return len(ids)

    def count(self, doc_type: str, document_id: int) -> int:
        return sum(1 for item in self.stored.values() if item["meta"]["document_id"] == document_id)

    def delete(self, doc_type: str, document_id: int) -> None:
        self.stored = {k: v for k, v in self.stored.items() if v["meta"]["document_id"] != document_id}


@dataclass
class PipelineDocument(FakeDocument):
    file_path: str = ""


class PipelineEndToEndTest(unittest.TestCase):
    """실제 PDF를 추출·청킹·저장·검증까지 파이프라인에 통과시켜 완료로 기록되는지 확인한다."""

    def run_pipeline(self, pdf: Path, document: PipelineDocument, models: list[str] | None) -> FakeStore:
        store = FakeStore(document)
        steps = IngestSteps(
            extract=extract_content,
            chunk=partial(chunk, models=models),
            tag=lambda chunks: chunks,
            embed=lambda texts: [[0.1, 0.2, 0.3] for _ in texts],
        )
        indexer = Indexer(upload=store.upload, count_stored=store.count, delete_document=store.delete)
        IngestPipeline(store, steps, indexer).run(document.id)
        return store

    @unittest.skipUnless(SAFETY_PDF.is_file(), "safety pdf not found")
    def test_safety_pdf_completes_with_chunk_count(self) -> None:
        document = PipelineDocument("secure", 12, "안전기준", "안전기준.pdf", str(SAFETY_PDF))

        store = self.run_pipeline(SAFETY_PDF, document, None)

        status, error, chunk_count = store.statuses[-1]
        self.assertEqual((status, error), ("COMPLETED", None))
        self.assertEqual(chunk_count, len(store.stored))
        self.assertGreater(chunk_count, 300)
        meta = store.stored["12:p51:0"]["meta"]
        self.assertEqual((meta["source"], meta["doc_name"], meta["document_type"]), ("안전기준.pdf", "안전기준", "secure"))

    @unittest.skipUnless(ELTRON_PDF.is_file(), "Eltron pdf not found")
    def test_tech_pdf_completes_and_keeps_model_metadata(self) -> None:
        document = PipelineDocument("tech", 7, "엘트론", "엘트론.pdf", str(ELTRON_PDF))

        store = self.run_pipeline(ELTRON_PDF, document, ["ELVRO 3000", "HYDRO 501"])

        self.assertEqual(store.statuses[-1][0], "COMPLETED")
        models = {item["meta"].get("model") for item in store.stored.values()}
        self.assertEqual(models - {None}, {"ELVRO 3000", "HYDRO 501"})
        # 제품명이 없는 페이지(예: 4p 방폭 조작반 사진 설명)의 청크는 model 없이 저장된다.
        without_model = {item["meta"]["page"] for item in store.stored.values() if "model" not in item["meta"]}
        self.assertEqual(without_model, {4})

    @unittest.skipUnless(LUXEN_PDF.is_file(), "LUXEN pdf not found")
    def test_pipeline_without_models_still_completes(self) -> None:
        document = PipelineDocument("tech", 8, "LUXEN", "LUXEN.pdf", str(LUXEN_PDF))

        store = self.run_pipeline(LUXEN_PDF, document, None)

        self.assertEqual(store.statuses[-1][0], "COMPLETED")
        self.assertTrue(all("model" not in item["meta"] for item in store.stored.values()))


@unittest.skipUnless(
    SAFETY_PDF.is_file() and ELTRON_PDF.is_file() and LUXEN_PDF.is_file(), "data/pdfs/ pdfs not found"
)
class RealPdfIndexerCompatibilityTest(unittest.TestCase):
    """실제 PDF 3개의 청크가 박정환의 Indexer.prepare() 검증을 통과하고 ChromaDB 규칙을 지키는지 확인한다."""

    @classmethod
    def setUpClass(cls) -> None:
        from features.processing.pdf_content import extract_pdf_content

        cls.cases = [
            (FakeDocument("secure", 12, "안전기준", "안전기준.pdf"), extract_pdf_content(SAFETY_PDF), None),
            (
                FakeDocument("tech", 7, "엘트론엘리베이터_기술사양서", "엘트론엘리베이터_기술사양서.pdf"),
                extract_pdf_content(ELTRON_PDF),
                ["ELVRO 3000", "HYDRO 501"],
            ),
            (
                FakeDocument("tech", 8, "Passenger Elevator_LUXEN NEW YZER_2406", "Passenger Elevator_LUXEN NEW YZER_2406.pdf"),
                extract_pdf_content(LUXEN_PDF),
                ["LUXEN", "NEW YZER"],
            ),
        ]

    def test_chunks_pass_indexer_prepare(self) -> None:
        for document, content, models in self.cases:
            chunks = chunk(document, content, models)
            records = Indexer().prepare(document.id, document.doc_type, chunks)

            self.assertEqual(len(records), len(chunks), document.title)
            self.assertEqual([r.id for r in records], [c.chunk_id for c in chunks], document.title)

    def test_every_text_page_has_chunks_and_no_unreadable_glyphs(self) -> None:
        for document, content, models in self.cases:
            chunks = chunk(document, content, models)
            pages = {c.metadata["page"] for c in chunks}

            self.assertGreater(len(pages), len(content.pages) // 2, document.title)
            self.assertEqual([c.chunk_id for c in chunks if re.search("[-]", c.text)], [], document.title)


if __name__ == "__main__":
    unittest.main()
