import unittest
from dataclasses import dataclass, field

from features.processing.indexer import COLLECTIONS, Indexer, IndexingError, Record


@dataclass
class FakeChunk:
    text: str
    metadata: dict = field(default_factory=dict)


def meta(page=1, chunk=0, **extra):
    """필수 메타데이터를 채운 dict. 문서 ID 7, 기술 문서 기준이다."""
    return {"source": "a.pdf", "page": page, "chunk": chunk, "document_id": 7,
            "document_type": "tech", **extra}


class PrepareTest(unittest.TestCase):
    def test_builds_ids_and_keeps_metadata(self):
        chunks = [
            FakeChunk("본문1", meta(1, 0, part="브레이크, 캘리퍼", task="교체, 점검")),
            FakeChunk("본문2", meta(2, 0)),
        ]
        records = Indexer().prepare(7, "tech", chunks)
        self.assertEqual([r.id for r in records], ["7:p1:0", "7:p2:0"])
        self.assertEqual(records[0].metadata["part"], "브레이크, 캘리퍼")
        self.assertEqual(records[0].metadata["task"], "교체, 점검")
        self.assertEqual(records[1].text, "본문2")

    def test_drops_none_values_without_changing_input(self):
        original = meta(1, 0, clause=None, model="CR-100")
        records = Indexer().prepare(7, "tech", [FakeChunk("본문", original)])
        self.assertNotIn("clause", records[0].metadata)
        self.assertEqual(records[0].metadata["model"], "CR-100")
        self.assertIsNone(original["clause"])

    def test_drops_blank_strings_but_keeps_values(self):
        original = meta(1, 0, part="", task="   ", model="CR-100", clause="")
        records = Indexer().prepare(7, "tech", [FakeChunk("본문", original)])
        metadata = records[0].metadata
        for key in ("part", "task", "clause"):
            self.assertNotIn(key, metadata)
        self.assertEqual(metadata["model"], "CR-100")
        self.assertEqual(original["part"], "")

    def test_keeps_zero_and_false_values(self):
        records = Indexer().prepare(7, "tech", [FakeChunk("본문", meta(1, 0, score=0, flag=False))])
        self.assertEqual(records[0].metadata["score"], 0)
        self.assertIs(records[0].metadata["flag"], False)

    def test_rejects_list_tags(self):
        """태그는 쉼표로 이은 문자열이다. 옛 방식의 리스트는 저장하지 않는다."""
        with self.assertRaisesRegex(ValueError, "unsupported type"):
            Indexer().prepare(7, "tech", [FakeChunk("본문", meta(part=["브레이크"]))])

    def test_rejects_missing_required_key(self):
        bad = meta()
        del bad["chunk"]
        with self.assertRaisesRegex(ValueError, "missing metadata"):
            Indexer().prepare(7, "tech", [FakeChunk("본문", bad)])

    def test_rejects_wrong_types(self):
        for bad in (meta(page="1"), meta(page=0), meta(page=True), meta(chunk=-1), meta(chunk=1.5)):
            with self.assertRaises(ValueError):
                Indexer().prepare(7, "tech", [FakeChunk("본문", bad)])

    def test_rejects_other_document_or_type(self):
        with self.assertRaises(ValueError):
            Indexer().prepare(8, "tech", [FakeChunk("본문", meta())])
        with self.assertRaises(ValueError):
            Indexer().prepare(7, "secure", [FakeChunk("본문", meta())])
        with self.assertRaises(ValueError):
            Indexer().prepare(7, "unknown", [FakeChunk("본문", meta())])

    def test_rejects_duplicate_chunk_id(self):
        chunks = [FakeChunk("가", meta(1, 0)), FakeChunk("나", meta(1, 0))]
        with self.assertRaisesRegex(ValueError, "duplicate chunk id"):
            Indexer().prepare(7, "tech", chunks)

    def test_rejects_empty_text_and_unsupported_value(self):
        with self.assertRaises(ValueError):
            Indexer().prepare(7, "tech", [FakeChunk("  ", meta())])
        with self.assertRaisesRegex(ValueError, "unsupported type"):
            Indexer().prepare(7, "tech", [FakeChunk("본문", meta(extra={"a": 1}))])


class SaveVerifyRemoveTest(unittest.TestCase):
    def test_save_sends_records_to_the_collection_of_the_doc_type(self):
        calls = []
        indexer = Indexer(upload=lambda *args: calls.append(args) or len(args[2]))
        records = [Record("7:p1:0", "가", {"page": 1}), Record("7:p1:1", "나", {"page": 1})]
        self.assertEqual(indexer.save("secure", records, [[0.1, 0.2], [0.3, 0.4]]), 2)
        doc_type, collection, ids, vectors, texts, metadatas = calls[0]
        self.assertEqual((doc_type, collection), ("secure", COLLECTIONS["secure"]))
        self.assertEqual(ids, ["7:p1:0", "7:p1:1"])
        self.assertEqual(texts, ["가", "나"])
        self.assertEqual(vectors[1], [0.3, 0.4])

    def test_save_rejects_mismatched_vectors_before_uploading(self):
        calls = []
        indexer = Indexer(upload=lambda *args: calls.append(args))
        records = [Record("7:p1:0", "가", {})]
        with self.assertRaises(ValueError):
            indexer.save("tech", records, [])
        with self.assertRaises(ValueError):
            indexer.save("tech", records * 2, [[0.1], [0.1, 0.2]])
        self.assertEqual(calls, [])

    def test_verify(self):
        indexer = Indexer(count_stored=lambda doc_type, document_id: 3)
        indexer.verify("tech", 7, 3)
        with self.assertRaises(IndexingError):
            indexer.verify("tech", 7, 4)

    def test_remove_document(self):
        calls = []
        indexer = Indexer(delete_document=lambda doc_type, document_id: calls.append((doc_type, document_id)))
        indexer.remove_document("secure", 7)
        self.assertEqual(calls, [("secure", 7)])
        with self.assertRaises(ValueError):
            indexer.remove_document("unknown", 7)


if __name__ == "__main__":
    unittest.main()
