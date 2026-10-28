import unittest

from core.schemas import SourceView
from features.qa.source_service import SourceService


def chunk(source, page, number, text, **extra):
    """rag_ingest가 만드는 모양의 청크."""
    return {"id": f"{source}:p{page}:{number}", "text": text,
            "metadata": {"source": source, "page": page, "chunk": number, **extra}}


MANUAL = [
    chunk("m.pdf", 3, 0, "3쪽 첫 문단"),
    chunk("m.pdf", 3, 1, "3쪽 둘째 문단"),
    chunk("m.pdf", 3, 2, "3쪽 셋째 문단"),
    chunk("m.pdf", 4, 0, "4쪽 첫 문단"),
]
SAFETY = [chunk("s.pdf", 3, 0, "안전 3쪽", doc_name="엘리베이터 안전기준", department="안전팀", clause="9.1")]


class GetSourceTest(unittest.TestCase):
    def setUp(self):
        self.service = SourceService([*MANUAL, *SAFETY])

    def test_returns_text_with_neighbors(self):
        self.assertEqual(
            self.service.get_source("m.pdf:p3:1"),
            SourceView("m.pdf:p3:1", "3쪽 둘째 문단", "3쪽 첫 문단", "3쪽 셋째 문단", "m.pdf", 3),
        )

    def test_edges_have_empty_neighbors(self):
        first = self.service.get_source("m.pdf:p3:0")
        last = self.service.get_source("m.pdf:p3:2")
        self.assertEqual((first.before, last.after), ("", ""))

    def test_neighbors_stay_in_same_page_and_document(self):
        view = self.service.get_source("m.pdf:p4:0")
        self.assertEqual((view.before, view.after), ("", ""))  # 3쪽 청크나 s.pdf 3쪽은 앞뒤가 아니다

    def test_uses_metadata_name_department_and_clause(self):
        view = self.service.get_source("s.pdf:p3:0")
        self.assertEqual((view.doc_name, view.department, view.clause), ("엘리베이터 안전기준", "안전팀", "9.1"))

    def test_missing_metadata_falls_back(self):
        view = SourceService([{"id": "x", "text": "본문"}]).get_source("x")
        self.assertEqual((view.doc_name, view.page, view.department, view.clause), ("", None, "", ""))

    def test_unknown_id_raises_lookup_error(self):
        with self.assertRaises(LookupError):
            self.service.get_source("없는:p1:0")


if __name__ == "__main__":
    unittest.main()