"""업로드·삭제 화면의 동작(필수값 확인, 등록 호출, 오류 문구)을 확인한다. DB·ChromaDB·알림은 가짜로 바꾼다."""

import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
