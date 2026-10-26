import unittest
import unittest.mock

from sqlalchemy import create_engine

from util import mysql_connection as db


class MysqlConnectionTest(unittest.TestCase):
    """쿼리 함수의 동작을 인메모리 SQLite 엔진으로 검증한다. MySQL 서버는 쓰지 않는다."""

    def setUp(self) -> None:
        """테이블이 있는 빈 인메모리 DB 엔진을 만든다."""
        self.engine = create_engine("sqlite://")
        db.execute("CREATE TABLE doc (id INTEGER, name TEXT)", engine=self.engine)

    def test_check_connection(self):
        self.assertTrue(db.check_connection(self.engine))

    def test_insert_then_fetch_with_params(self):
        n = db.execute("INSERT INTO doc VALUES (:id, :name)", {"id": 1, "name": "서버 점검"}, self.engine)
        rows = db.fetch_all("SELECT * FROM doc WHERE id = :id", {"id": 1}, self.engine)
        self.assertEqual((n, rows), (1, [{"id": 1, "name": "서버 점검"}]))

    def test_injection_text_is_treated_as_value(self):
        db.execute("INSERT INTO doc VALUES (1, 'a')", engine=self.engine)
        rows = db.fetch_all("SELECT * FROM doc WHERE name = :n", {"n": "a' OR '1'='1"}, self.engine)
        self.assertEqual(rows, [])

    def test_failed_execute_rolls_back(self):
        with self.assertRaises(Exception):
            db.execute("INSERT INTO missing_table VALUES (1)", engine=self.engine)
        self.assertEqual(db.fetch_all("SELECT * FROM doc", engine=self.engine), [])

    def test_missing_engine_raises(self):
        with unittest.mock.patch.object(db, "default_engine", None):
            with self.assertRaises(RuntimeError):
                db.check_connection()


if __name__ == "__main__":
    unittest.main()
