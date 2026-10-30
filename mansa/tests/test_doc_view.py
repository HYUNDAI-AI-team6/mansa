import unittest
from unittest import mock

from ui import components as ui
from ui import doc_view

DOCS = [
    {"id": 1, "title": "모델 A 매뉴얼", "type": "기술 문서", "dept": "유지보수팀", "status": "완료", "date": "10/21"},
    {"id": 2, "title": "추락 방지 지침", "type": "안전 문서", "dept": "안전팀", "status": "완료", "date": "10/22"},
    {"id": 3, "title": "모델 B 매뉴얼", "type": "기술 문서", "dept": "-", "status": "완료", "date": "10/23"},
    {"id": 4, "title": "처리 중 문서", "type": "기술 문서", "dept": "검사팀", "status": "처리 중", "date": "10/24"},
    {"id": 5, "title": "실패 문서", "type": "안전 문서", "dept": "검사팀", "status": "실패", "date": "10/25"},
]


def load_completed(docs: list[dict] = DOCS) -> list[dict]:
    with mock.patch("ui.documents.load_docs", return_value=docs):
        return doc_view.load_completed()


class LoadCompletedTest(unittest.TestCase):
    def test_only_completed_documents_are_kept(self):
        self.assertEqual([d["id"] for d in load_completed()], [1, 2, 3])

    def test_no_completed_documents_shows_empty_message(self):
        html = doc_view.table(load_completed(DOCS[3:]), "전체", "", "")
        self.assertIn("조건에 맞는 문서가 없어요", html)


class TitleTest(unittest.TestCase):
    def test_titles_are_plain_text_without_a_sample_pdf(self):
        html = doc_view.table(load_completed(), "전체", "", "")
        self.assertIn("모델 A 매뉴얼", html)
        self.assertNotIn("data-pdf", html)
        self.assertNotIn("doc-open", html)


class ChoicesTest(unittest.TestCase):
    def test_dept_choices_come_from_documents_without_dash(self):
        self.assertEqual(
            doc_view.dept_choices(load_completed()),
            [("부서 전체", ""), ("안전팀", "안전팀"), ("유지보수팀", "유지보수팀")],
        )

    def test_type_chips_count_completed_documents(self):
        self.assertEqual(
            doc_view.type_choices(load_completed()),
            [("전체 3", "전체"), ("기술 문서 2", "기술 문서"), ("안전 문서 1", "안전 문서")],
        )


class TableTest(unittest.TestCase):
    def test_type_and_keyword_filter(self):
        html = doc_view.table(load_completed(), "안전 문서", "", "추락")
        self.assertIn("추락 방지 지침", html)
        self.assertNotIn("모델 A 매뉴얼", html)

    def test_dept_filter(self):
        html = doc_view.table(load_completed(), "전체", "유지보수팀", "")
        self.assertIn("모델 A 매뉴얼", html)
        self.assertNotIn("모델 B 매뉴얼", html)

    def test_dash_dept_is_shown(self):
        html = doc_view.table(load_completed(), "전체", "", "모델 B")
        self.assertIn("모델 B 매뉴얼", html)
        self.assertIn(ui.dept_tag("-"), html)


if __name__ == "__main__":
    unittest.main()
