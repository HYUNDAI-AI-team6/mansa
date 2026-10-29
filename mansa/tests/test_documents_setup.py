import re
import unittest
from pathlib import Path

import config

APP_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS = APP_DIR / "migrations"
FILE_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def sql_files() -> list[Path]:
    return sorted(MIGRATIONS.glob("*.sql"))


def statements(path: Path) -> str:
    """주석(--)을 뺀 SQL 본문."""
    return "\n".join(line for line in path.read_text(encoding="utf-8").splitlines() if not line.strip().startswith("--"))


class MigrationFilesTest(unittest.TestCase):
    def test_files_are_numbered_without_gaps_from_0001(self) -> None:
        numbers = [int(FILE_NAME.fullmatch(path.name).group(1)) for path in sql_files()]

        self.assertEqual(numbers, list(range(1, len(numbers) + 1)))

    def test_every_file_ends_each_statement_and_never_removes_data(self) -> None:
        for path in sql_files():
            body = statements(path)
            with self.subTest(path.name):
                self.assertTrue(body.strip().endswith(";"))
                # 외래키 설정의 ON DELETE는 삭제 문장이 아니므로 DELETE FROM만 본다.
                self.assertIsNone(re.search(r"\b(DROP|TRUNCATE)\b|\bDELETE\s+FROM\b", body, re.IGNORECASE))

    def test_0001_creates_documents_info_like_the_live_table(self) -> None:
        body = statements(MIGRATIONS / "0001_create_documents_info.sql")

        self.assertIn("CREATE TABLE IF NOT EXISTS `documents_info`", body)
        for expected in (
            "`id` bigint NOT NULL AUTO_INCREMENT",
            "`filename` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL",
            "`document_type` enum('tech','secure') NOT NULL",
            "`status` enum('PROCESSING','COMPLETED','FAILED') NOT NULL DEFAULT 'PROCESSING'",
            "UNIQUE KEY `uk_documents_filename_type` (`filename`,`document_type`)",
            "KEY `idx_documents_status_upload` (`status`,`upload_at`)",
            "REFERENCES `departments` (`id`) ON DELETE RESTRICT",
        ):
            self.assertIn(expected, body)

    def test_0002_adds_the_two_columns_once(self) -> None:
        body = statements(MIGRATIONS / "0002_add_chunk_count_error_message.sql")

        self.assertEqual(body.count("ADD COLUMN `chunk_count` int NULL"), 1)
        self.assertEqual(body.count("ADD COLUMN `error_message` varchar(1000) NULL"), 1)
        self.assertEqual(body.count("ALTER TABLE `documents_info`"), 1)


class PdfStorageDirTest(unittest.TestCase):
    def test_storage_dir_is_an_absolute_path(self) -> None:
        self.assertIsInstance(config.PDF_STORAGE_DIR, Path)
        self.assertTrue(config.PDF_STORAGE_DIR.is_absolute())

    def test_uploaded_pdfs_are_ignored_by_git(self) -> None:
        gitignore = (config.REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

        self.assertIn("mansa/data/documents/", gitignore)

    def test_env_example_documents_the_variable(self) -> None:
        self.assertIn("PDF_STORAGE_DIR", (APP_DIR / ".env.example").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
