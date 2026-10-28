import unittest

from features.master.departments import MAX_LENGTH, DepartmentService
from features.master.errors import DuplicateError, NotFoundError, ValidationError
from features.master.models import DepartmentInput
from tests.fake_master_db import FakeMasterDb


def make(departments=None):
    db = FakeMasterDb(departments=departments)
    return db, DepartmentService(db.fetch_all, db.execute)


class DepartmentServiceTest(unittest.TestCase):
    def test_list_all_in_registration_order(self):
        _, service = make([{"id": 2, "name": "안전팀", "description": "법규"},
                           {"id": 1, "name": "유지보수팀", "description": "매뉴얼"}])
        self.assertEqual([d.name for d in service.list_all()], ["유지보수팀", "안전팀"])
        self.assertEqual(make()[1].list_all(), [])

    def test_create_trims_saves_and_returns_the_new_department(self):
        db, service = make()
        created = service.create(DepartmentInput("  검사·품질팀 ", " 검사 절차서 "))
        self.assertEqual((created.id, created.name, created.description), (1, "검사·품질팀", "검사 절차서"))
        insert = [q for q in db.queries if q[0].startswith("INSERT")][0]
        self.assertEqual(insert[1]["name"], "검사·품질팀")

    def test_description_may_be_empty(self):
        self.assertEqual(make()[1].create(DepartmentInput("안전팀")).description, "")

    def test_create_rejects_empty_long_and_duplicate_names(self):
        db, service = make([{"id": 1, "name": "안전팀", "description": ""}])
        too_long = "가" * (MAX_LENGTH + 1)
        for bad in (DepartmentInput(""), DepartmentInput("   "), DepartmentInput(too_long),
                    DepartmentInput("팀", "나" * (MAX_LENGTH + 1))):
            with self.assertRaises(ValidationError):
                service.create(bad)
        with self.assertRaises(DuplicateError):
            service.create(DepartmentInput("안전팀"))
        self.assertEqual(len(db.departments), 1)

    def test_values_are_passed_as_parameters_not_in_sql(self):
        db, service = make()
        service.create(DepartmentInput("x'; DROP TABLE departments; --"))
        for sql, _ in db.queries:
            self.assertNotIn("DROP", sql)

    def test_update_changes_name_and_description(self):
        db, service = make([{"id": 1, "name": "안전팀", "description": "법규"}])
        updated = service.update(1, DepartmentInput("안전관리팀", "지침"))
        self.assertEqual((updated.name, updated.description), ("안전관리팀", "지침"))
        self.assertEqual(db.departments[0]["name"], "안전관리팀")

    def test_update_can_keep_its_own_name_but_not_take_anothers(self):
        _, service = make([{"id": 1, "name": "안전팀", "description": ""},
                           {"id": 2, "name": "유지보수팀", "description": ""}])
        self.assertEqual(service.update(1, DepartmentInput("안전팀", "설명 추가")).description, "설명 추가")
        with self.assertRaises(DuplicateError):
            service.update(1, DepartmentInput("유지보수팀"))

    def test_update_unknown_department_raises_not_found(self):
        with self.assertRaises(NotFoundError):
            make()[1].update(9, DepartmentInput("안전팀"))


if __name__ == "__main__":
    unittest.main()
