import unittest

from scripts import seed
from tests.fake_master_db import FakeMasterDb


def writes(db):
    """DB를 바꾼 쿼리(INSERT·UPDATE)만 골라낸다."""
    return [q for q, _ in db.queries if not q.startswith("SELECT")]


class SeedTest(unittest.TestCase):
    def test_dry_run_reports_but_changes_nothing(self):
        db = FakeMasterDb()
        report = seed.run(False, db.fetch_all, db.execute)
        self.assertEqual(writes(db), [])
        self.assertEqual(len(report), 1)
        self.assertTrue(report[0].startswith("[dry-run] departments to add:"))
        self.assertIn("안전팀", report[0])

    def test_apply_inserts_missing_departments(self):
        db = FakeMasterDb()
        seed.run(True, db.fetch_all, db.execute)
        expected = [d.name for d in seed.DEMO_DEPARTMENTS]
        self.assertEqual([d["name"] for d in db.departments], expected)

    def test_running_twice_does_not_duplicate(self):
        db = FakeMasterDb()
        seed.run(True, db.fetch_all, db.execute)
        report = seed.run(True, db.fetch_all, db.execute)
        self.assertEqual(len(db.departments), len(seed.DEMO_DEPARTMENTS))
        self.assertEqual(report, ["departments to add: []"])

    def test_existing_department_is_kept_as_is(self):
        db = FakeMasterDb(departments=[{"id": 7, "name": "안전팀", "description": "기존 설명"}])
        seed.run(True, db.fetch_all, db.execute)
        self.assertEqual(db.departments[0]["description"], "기존 설명")
        self.assertEqual(len(db.departments), 3)


if __name__ == "__main__":
    unittest.main()
