"""업로드·삭제 화면의 동작(필수값 확인, 등록 호출, 오류 문구)을 확인한다. DB·ChromaDB·알림은 가짜로 바꾼다."""

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from features.documents.errors import DocumentNotFoundError, DocumentStorageError, DuplicateDocumentError
from features.processing.deletion import DeletionError, DocumentBusyError
from ui import documents, upload


def collect(generator) -> list:
    return list(generator)


def file_state(path="/tmp/gradio/ab12/엘트론.pdf"):
    return {"file": {"name": "엘트론.pdf", "size": "1KB", "path": path}, "type": "기술 문서"}


class UploadErrorMessageTest(unittest.TestCase):
    def test_each_error_has_its_own_user_facing_message(self):
        duplicate = upload.upload_error_message(DuplicateDocumentError(5))
        self.assertIn("이미 등록된 문서", duplicate)
        self.assertIn("삭제한 뒤 다시", duplicate)
        self.assertIn("올린 내용을 확인", upload.upload_error_message(ValueError("only PDF files can be registered")))
        self.assertIn("파일을 저장하지 못", upload.upload_error_message(DocumentStorageError()))
        self.assertIn("등록하지 못", upload.upload_error_message(RuntimeError("db is down")))

    def test_internal_error_text_is_never_shown(self):
        for exc in (ValueError("secret detail"), RuntimeError("password=1234"), DocumentStorageError("/srv/x")):
            self.assertNotIn(str(exc), upload.upload_error_message(exc))


class DepartmentIdTest(unittest.TestCase):
    def test_finds_the_id_by_name(self):
        service = SimpleNamespace(list_all=lambda: [SimpleNamespace(id=1, name="안전팀"), SimpleNamespace(id=3, name="유지보수팀")])
        with mock.patch.object(upload, "_departments", return_value=service):
            self.assertEqual(upload._department_id("유지보수팀"), 3)
            with self.assertRaises(ValueError):
                upload._department_id("없는팀")


class PickFileTest(unittest.TestCase):
    def test_keeps_the_path_so_the_upload_can_use_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "문서.pdf"
            pdf.write_bytes(b"%PDF-1.7\n")
            state, cleared, _ = upload._pick_file(str(pdf), upload._empty())
        self.assertEqual(state["file"]["name"], "문서.pdf")
        self.assertEqual(state["file"]["path"], str(pdf))
        self.assertIsNone(cleared)


class UploadLimitTest(unittest.TestCase):
    def test_the_screen_and_the_service_share_the_100mb_limit(self):
        from features.documents import service

        self.assertEqual(upload.MAX_MB, 100)
        self.assertEqual(service.MAX_PDF_BYTES, upload.MAX_MB * 1024 * 1024)  # 화면 값을 바꾸면 서비스도 같이 바꾼다
        self.assertIn(f"최대 {upload.MAX_MB}MB", upload.dropzone_html())

    def test_the_support_guide_tells_the_same_limit(self):
        import json
        from pathlib import Path

        guides = json.loads((Path(upload.__file__).parents[1] / "data" / "support" / "guides.json").read_text(encoding="utf-8"))
        steps = next(g for g in guides if g["id"] == "upload")["steps"]
        self.assertTrue(any(f"{upload.MAX_MB}MB 이하" in step for step in steps))


class UploadTest(unittest.TestCase):
    def setUp(self):
        self.warn = mock.patch.object(upload.ui, "warn").start()
        self.notify = mock.patch.object(upload.ui, "notify").start()
        self.reset = mock.patch.object(upload, "_reset", return_value=("e", "f", "d", "t", "r")).start()
        self.register_patch = mock.patch.object(upload, "_register")
        self.register = self.register_patch.start()
        self.addCleanup(mock.patch.stopall)

    def test_missing_values_are_reported_and_nothing_is_registered(self):
        steps = collect(upload._upload({"file": None, "type": ""}, "", {}))
        self.assertEqual(len(steps), 1)
        self.assertEqual(len(steps[0]), 8)
        self.warn.assert_called_once_with("아직 정하지 않았어요: 파일 · 문서 유형 · 소속 부서")
        self.register.assert_not_called()

    def test_a_successful_upload_registers_notifies_and_resets_the_form(self):
        steps = collect(upload._upload(file_state(), "유지보수팀", {}))
        self.register.assert_called_once_with(file_state(), "유지보수팀")
        self.notify.assert_called_once()
        self.assertEqual([len(step) for step in steps], [8, 8])  # 업로드 중 → 완료
        self.reset.assert_called_once()
        self.warn.assert_not_called()

    def test_a_duplicate_is_explained_and_the_form_is_kept(self):
        self.register.side_effect = DuplicateDocumentError(5)
        steps = collect(upload._upload(file_state(), "유지보수팀", {}))
        self.assertIn("이미 등록된 문서", self.warn.call_args.args[0])
        self.assertEqual(len(steps), 2)
        self.reset.assert_not_called()  # 입력을 그대로 둔다
        self.notify.assert_not_called()

    def test_an_unexpected_error_is_logged_and_the_user_gets_a_plain_message(self):
        self.register.side_effect = RuntimeError("db is down")
        with self.assertLogs("ui.upload", level="ERROR"):
            collect(upload._upload(file_state(), "유지보수팀", {}))
        self.assertIn("등록하지 못", self.warn.call_args.args[0])
        self.assertNotIn("db is down", self.warn.call_args.args[0])

    def test_register_sends_the_file_type_code_and_department_id_to_the_workflow(self):
        self.register_patch.stop()
        flow = mock.Mock()
        service = SimpleNamespace(list_all=lambda: [SimpleNamespace(id=3, name="유지보수팀")])
        with mock.patch("features.processing.workflow.default_workflow", return_value=flow), \
                mock.patch.object(upload, "_departments", return_value=service):
            upload._register(file_state(), "유지보수팀")
            upload._register({**file_state(), "type": "안전 문서"}, "유지보수팀")
        self.assertEqual(
            [call.args for call in flow.upload.call_args_list],
            [("/tmp/gradio/ab12/엘트론.pdf", "엘트론.pdf", "tech", 3), ("/tmp/gradio/ab12/엘트론.pdf", "엘트론.pdf", "secure", 3)],
        )


class DeleteTest(unittest.TestCase):
    def setUp(self):
        self.warn = mock.patch.object(documents.ui, "warn").start()
        self.notify = mock.patch.object(documents.ui, "notify").start()
        self.flow = mock.Mock()
        mock.patch("features.processing.workflow.default_workflow", return_value=self.flow).start()
        mock.patch.object(documents, "load_docs", return_value=[]).start()
        self.addCleanup(mock.patch.stopall)
        self.evt = SimpleNamespace(index=7.0)  # 화면이 보내는 id (JS 숫자)

    def delete(self):
        return documents._delete("", self.evt)

    def test_deletes_by_integer_document_id_and_redraws(self):
        stats, table = self.delete()
        self.flow.delete.assert_called_once_with(7)
        self.assertIsInstance(self.flow.delete.call_args.args[0], int)
        self.notify.assert_called_once_with("문서를 삭제했어요")
        self.assertIn("stats", stats)

    def test_a_missing_original_file_is_mentioned(self):
        self.flow.delete.return_value = SimpleNamespace(pdf_existed=False, record_existed=True)
        self.delete()
        self.notify.assert_called_once_with("문서를 삭제했어요. 원본 파일은 이미 없었어요")

    def test_an_already_deleted_document_is_just_reported(self):
        self.flow.delete.side_effect = DocumentNotFoundError(7)
        self.delete()
        self.notify.assert_called_once_with("이미 삭제된 문서예요")
        self.warn.assert_not_called()

    def test_a_document_being_processed_shows_the_reason(self):
        self.flow.delete.side_effect = DocumentBusyError("처리 중인 문서는 삭제할 수 없어요. 처리가 끝난 뒤 다시 시도해 주세요")
        self.delete()
        self.assertIn("처리 중인 문서", self.warn.call_args.args[0])

    def test_a_failed_step_shows_its_message(self):
        self.flow.delete.side_effect = DeletionError("원본 파일을 지우지 못했어요. 잠시 후 다시 시도해 주세요")
        self.delete()
        self.assertIn("원본 파일", self.warn.call_args.args[0])

    def test_an_unexpected_error_is_logged_and_hidden_from_the_user(self):
        self.flow.delete.side_effect = RuntimeError("db is down")
        with self.assertLogs("ui.documents", level="ERROR"):
            self.delete()
        self.assertNotIn("db is down", self.warn.call_args.args[0])
        self.notify.assert_not_called()


class LoadDocsTest(unittest.TestCase):
    def rows(self, **extra):
        row = {"id": 5, "filename": "엘트론.pdf", "document_type": "tech", "status": "COMPLETED", "dept": "기술팀",
               "chunk_count": 27, "error_message": None, "upload_at": datetime(2026, 10, 30, 9, 0)}
        return [{**row, **extra}]

    def load(self, rows):
        fake = SimpleNamespace(fetch_all=lambda sql, params=None: rows)
        with mock.patch.dict(sys.modules, {"util.mysql_connection": fake}):
            return documents.load_docs()

    def test_the_query_reads_the_chunk_count_and_the_failure_reason(self):
        self.assertIn("d.chunk_count", documents.SELECT_DOCS)
        self.assertIn("d.error_message", documents.SELECT_DOCS)

    def test_results_carry_the_chunk_count_and_reason(self):
        done = self.load(self.rows())[0]
        failed = self.load(self.rows(status="FAILED", chunk_count=None, error_message="PDF를 열 수 없어요"))[0]
        self.assertEqual((done["chunks"], done["error"]), (27, None))
        self.assertEqual((failed["chunks"], failed["error"]), (None, "PDF를 열 수 없어요"))


class TableTest(unittest.TestCase):
    def doc(self, status: str, title: str = "엘트론.pdf", **extra) -> dict:
        return {"id": 3, "title": title, "type": "기술 문서", "dept": "유지보수팀", "status": status,
                "chunks": None, "error": None, "date": "10/30", **extra}

    def test_a_completed_row_shows_the_chunk_count(self):
        self.assertIn("<em>27개</em>", documents.table([self.doc("완료", chunks=27)]))

    def test_a_row_without_a_chunk_count_shows_a_dash(self):
        # 이전에 처리한 문서(NULL), 처리 중, 실패 문서
        for doc in (self.doc("완료"), self.doc("처리 중"), self.doc("실패", chunks=5)):
            with self.subTest(status=doc["status"]):
                html = documents.table([doc])
                self.assertIn("<em>-</em>", html)
                self.assertNotIn("개</em>", html)

    def test_the_chunk_count_column_lines_up_with_the_cells(self):
        html = documents.table([self.doc("완료", chunks=1)])
        self.assertEqual(html.count("grid-template-columns"), 2)  # 머리글과 한 줄
        self.assertEqual(len(documents.COLUMNS), 7)

    def test_a_failed_row_has_an_info_mark_whose_tooltip_shows_the_reason_and_the_retry_hint(self):
        html = documents.table([self.doc("실패", error="PDF를 열 수 없어요")])
        self.assertIn('class="fail-info"', html)
        self.assertIn('<span class="fail-tip" aria-hidden="true"><span>PDF를 열 수 없어요</span>', html)
        self.assertIn('<span class="hint">삭제한 뒤 다시 올려 주세요</span>', html)

    def test_the_info_mark_is_not_focusable_so_the_tooltip_never_sticks(self):
        html = documents.table([self.doc("실패", error="사유")])
        self.assertNotIn("tabindex", html)
        self.assertNotIn("<button", html.split("fail-info")[1].split("fail-tip")[0])

    def test_screen_readers_get_the_reason_and_the_hint_from_the_label(self):
        html = documents.table([self.doc("실패", error="PDF를 열 수 없어요")])
        self.assertIn('aria-label="실패 사유: PDF를 열 수 없어요. 삭제한 뒤 다시 올려 주세요"', html)
        self.assertIn('class="fail-tip" aria-hidden="true"', html)

    def test_the_reason_is_not_printed_next_to_the_title(self):
        # 사유는 말풍선 안에만 있고 이름 옆에 글자로 붙지 않는다
        html = documents.table([self.doc("실패", error="PDF를 열 수 없어요")])
        self.assertEqual(html.count("PDF를 열 수 없어요"), 2)  # 말풍선과 화면 낭독기용 라벨 하나씩

    def test_a_failed_row_without_a_reason_only_shows_the_retry_hint_in_the_tooltip(self):
        html = documents.table([self.doc("실패")])
        self.assertIn('class="fail-info"', html)
        self.assertIn('<span class="fail-tip" aria-hidden="true"><span class="hint">', html)

    def test_a_reason_with_nothing_visible_is_treated_as_no_reason(self):
        # 공백·줄바꿈·제로폭 공백뿐인 사유가 빈 줄로 말풍선 위쪽에 간격을 만들지 않는다
        for blank in ("", "   ", "\n", " \n\t ", "\u200b", "\u3000", " \u200b\n"):
            with self.subTest(blank=repr(blank)):
                html = documents.table([self.doc("실패", error=blank)])
                self.assertIn('<span class="fail-tip" aria-hidden="true"><span class="hint">', html)
                self.assertIn('aria-label="실패했어요. 삭제한 뒤 다시 올려 주세요"', html)

    def test_a_reason_with_visible_text_is_kept_trimmed(self):
        html = documents.table([self.doc("실패", error="  \n사유 있음\n ")])
        self.assertIn('<span class="fail-tip" aria-hidden="true"><span>사유 있음</span>', html)

    def test_the_reason_is_escaped(self):
        html = documents.table([self.doc("실패", error='<script>alert("x")</script>')])
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_the_reason_is_only_shown_for_failed_rows(self):
        html = documents.table([self.doc("완료", error="남아 있던 사유")])
        self.assertNotIn("남아 있던 사유", html)

    def test_a_failed_row_says_to_delete_and_upload_again(self):
        html = documents.table([self.doc("실패")])
        self.assertIn("삭제한 뒤 다시 올려 주세요", html)

    def test_only_failed_rows_have_the_info_mark(self):
        for status in ("완료", "처리 중"):
            with self.subTest(status=status):
                self.assertNotIn("fail-info", documents.table([self.doc(status, error="남은 사유")]))

    def test_other_rows_have_no_retry_hint(self):
        for status in ("완료", "처리 중"):
            with self.subTest(status=status):
                self.assertNotIn("다시 올려 주세요", documents.table([self.doc(status)]))

    def test_titles_do_not_open_a_sample_pdf(self):
        html = documents.table([self.doc("완료"), self.doc("처리 중", "b.pdf"), self.doc("실패", "c.pdf")])
        self.assertNotIn("data-pdf", html)
        self.assertNotIn("doc-open", html)
        self.assertIn("엘트론.pdf", html)

    def test_the_trash_button_still_carries_the_document_id(self):
        self.assertIn('data-i="3"', documents.table([self.doc("완료")]))


if __name__ == "__main__":
    unittest.main()
