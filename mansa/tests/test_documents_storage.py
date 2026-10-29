import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from features.documents.errors import DocumentStorageError
from features.documents.storage import PdfStorage

PDF = b"%PDF-1.7\n% test\n"


class StorageTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.storage = PdfStorage(self.root / "documents")
        self.upload = self.root / "업로드.pdf"
        self.upload.write_bytes(PDF)

    def stored(self) -> list[str]:
        return sorted(str(p.relative_to(self.root)) for p in (self.root / "documents").rglob("*") if p.is_file())


class PathTest(StorageTestCase):
    def test_path_uses_the_type_folder_and_the_document_id(self) -> None:
        self.assertEqual(self.storage.path_for(12, "secure"), self.root / "documents" / "secure" / "12.pdf")
        self.assertEqual(self.storage.path_for(7, "tech"), self.root / "documents" / "tech" / "7.pdf")

    def test_unknown_type_is_rejected_so_the_path_cannot_leave_the_folder(self) -> None:
        for bad in ("../x", "SPEC", "", "tech/.."):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.storage.path_for(1, bad)

    def test_bad_ids_are_rejected(self) -> None:
        for bad in (0, -1, True, "1", 1.5, None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.storage.path_for(bad, "tech")

    def test_default_base_dir_comes_from_config(self) -> None:
        self.assertEqual(PdfStorage().base_dir, Path(config.PDF_STORAGE_DIR))

    def test_nothing_is_created_by_computing_a_path(self) -> None:
        self.storage.path_for(1, "tech")

        self.assertFalse((self.root / "documents").exists())


class SaveTest(StorageTestCase):
    def test_save_temp_copies_the_upload_into_the_type_folder(self) -> None:
        temp = self.storage.save_temp(self.upload, "secure")

        self.assertEqual(temp.parent, self.root / "documents" / "secure")
        self.assertEqual(temp.read_bytes(), PDF)
        self.assertTrue(self.upload.exists())  # 원본은 그대로다

    def test_commit_renames_the_temp_file_to_the_document_id(self) -> None:
        temp = self.storage.save_temp(self.upload, "tech")

        path = self.storage.commit(temp, 5, "tech")

        self.assertEqual(path, self.root / "documents" / "tech" / "5.pdf")
        self.assertEqual(path.read_bytes(), PDF)
        self.assertFalse(temp.exists())
        self.assertEqual(self.stored(), ["documents/tech/5.pdf"])

    def test_commit_overwrites_a_leftover_file(self) -> None:
        self.storage.path_for(5, "tech").parent.mkdir(parents=True)
        self.storage.path_for(5, "tech").write_bytes(b"old")

        self.storage.commit(self.storage.save_temp(self.upload, "tech"), 5, "tech")

        self.assertEqual(self.storage.path_for(5, "tech").read_bytes(), PDF)

    def test_missing_source_raises_and_leaves_no_temp_file(self) -> None:
        with self.assertRaises(DocumentStorageError):
            self.storage.save_temp(self.root / "없는파일.pdf", "tech")

        self.assertEqual(self.stored(), [])

    def test_file_names_with_unusual_characters_are_not_used_in_the_path(self) -> None:
        odd = self.root / "../‮ evil;rm.pdf".replace("/", "_")
        odd.write_bytes(PDF)

        self.storage.commit(self.storage.save_temp(odd, "tech"), 3, "tech")

        self.assertEqual(self.stored(), ["documents/tech/3.pdf"])

    def test_failed_rename_raises_a_storage_error_and_keeps_the_temp_file(self) -> None:
        temp = self.storage.save_temp(self.upload, "tech")

        with mock.patch("features.documents.storage.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(DocumentStorageError):
                self.storage.commit(temp, 5, "tech")

        self.assertTrue(temp.exists())

    def test_discard_removes_the_temp_file_and_ignores_missing_ones(self) -> None:
        temp = self.storage.save_temp(self.upload, "tech")

        self.storage.discard(temp)
        self.storage.discard(temp)

        self.assertEqual(self.stored(), [])

    def test_discard_does_not_raise_when_the_file_cannot_be_removed(self) -> None:
        with mock.patch.object(Path, "unlink", side_effect=PermissionError):
            self.storage.discard(self.upload)  # 예외 없이 끝난다


class DeleteTest(StorageTestCase):
    def test_delete_removes_the_file_and_is_safe_to_repeat(self) -> None:
        self.storage.commit(self.storage.save_temp(self.upload, "secure"), 8, "secure")

        self.assertTrue(self.storage.delete(8))
        self.assertFalse(self.storage.delete(8))
        self.assertEqual(self.stored(), [])

    def test_delete_finds_the_file_in_either_type_folder(self) -> None:
        self.storage.commit(self.storage.save_temp(self.upload, "tech"), 2, "tech")
        self.storage.commit(self.storage.save_temp(self.upload, "secure"), 3, "secure")

        self.assertTrue(self.storage.delete(3))

        self.assertEqual(self.stored(), ["documents/tech/2.pdf"])

    def test_delete_without_any_file_or_folder_returns_false(self) -> None:
        self.assertFalse(self.storage.delete(99))

    def test_delete_does_not_touch_other_documents(self) -> None:
        self.storage.commit(self.storage.save_temp(self.upload, "tech"), 1, "tech")
        self.storage.commit(self.storage.save_temp(self.upload, "tech"), 11, "tech")

        self.storage.delete(1)

        self.assertEqual(self.stored(), ["documents/tech/11.pdf"])

    def test_delete_raises_a_storage_error_when_the_file_cannot_be_removed(self) -> None:
        self.storage.commit(self.storage.save_temp(self.upload, "tech"), 4, "tech")

        with mock.patch.object(Path, "unlink", side_effect=PermissionError("denied")):
            with self.assertRaises(DocumentStorageError):
                self.storage.delete(4)

    def test_delete_rejects_bad_ids(self) -> None:
        with self.assertRaises(ValueError):
            self.storage.delete(0)


if __name__ == "__main__":
    unittest.main()
