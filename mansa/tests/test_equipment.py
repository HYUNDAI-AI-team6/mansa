import tempfile
import unittest
from pathlib import Path

from features.master.equipment import EquipmentModelService, load_models
from features.master.errors import NotFoundError
from features.master.models import EquipmentModel, ModelFilter

HEADER = "maker,name,rated_speed,rated_load,usage,drive_type\n"
SAMPLE = HEADER + (
    "제조사,모델 A,105,750,승객용,\n"
    "제조사,모델 B,60,1000,화물용,기어드\n"
    "다른사,모델 C,,,승객용,\n"
)


class CsvCase(unittest.TestCase):
    def write_csv(self, text: str) -> Path:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "models.csv"
        path.write_text(text, encoding="utf-8")
        return path

    def service(self, text: str = SAMPLE) -> EquipmentModelService:
        return EquipmentModelService(self.write_csv(text))


class LoadModelsTest(CsvCase):
    def test_rows_become_models_with_ids_in_file_order(self):
        first, second, third = load_models(self.write_csv(SAMPLE))
        self.assertEqual(first, EquipmentModel(1, "제조사", "모델 A", "승객용", 105.0, 750, None, 0))
        self.assertIsInstance(first.rated_speed, float)
        self.assertEqual((second.id, second.drive_type), (2, "기어드"))
        self.assertEqual((third.rated_speed, third.rated_load), (None, None))
        self.assertEqual(first.display_id, "M-001")

    def test_rejects_missing_columns_blank_required_values_and_bad_numbers(self):
        cases = [
            "maker,name,usage\n제조사,모델,승객용\n",
            HEADER + ",모델,105,750,승객용,\n",
            HEADER + "제조사,모델,105,750,,\n",
            HEADER + "제조사,모델,빠름,750,승객용,\n",
            HEADER + "제조사,모델,105,많음,승객용,\n",
        ]
        for text in cases:
            with self.assertRaises(ValueError, msg=text):
                load_models(self.write_csv(text))

    def test_error_message_names_the_row(self):
        with self.assertRaisesRegex(ValueError, "row 2"):
            load_models(self.write_csv(HEADER + "a,b,1,1,승객용,\na,c,x,1,승객용,\n"))

    def test_rejects_duplicate_maker_and_name(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            load_models(self.write_csv(HEADER + "a,b,1,1,승객용,\na,b,2,2,승객용,\n"))

    def test_shipped_csv_is_valid(self):
        models = load_models()
        self.assertGreaterEqual(len(models), 1)
        self.assertEqual([m.id for m in models], list(range(1, len(models) + 1)))


class EquipmentModelServiceTest(CsvCase):
    def test_no_condition_returns_everything_in_order(self):
        self.assertEqual([m.name for m in self.service().list_models()], ["모델 A", "모델 B", "모델 C"])

    def test_conditions_are_anded(self):
        service = self.service()
        names = lambda condition: [m.name for m in service.list_models(condition)]
        self.assertEqual(names(ModelFilter(maker="제조사")), ["모델 A", "모델 B"])
        self.assertEqual(names(ModelFilter(speed_min=100)), ["모델 A"])
        self.assertEqual(names(ModelFilter(speed_max=60)), ["모델 B"])
        self.assertEqual(names(ModelFilter(load_min=800)), ["모델 B"])
        self.assertEqual(names(ModelFilter(maker="제조사", speed_min=50, load_max=800)), ["모델 A"])
        self.assertEqual(names(ModelFilter(maker="없는사")), [])

    def test_missing_values_drop_out_only_when_conditioned(self):
        service = self.service()
        self.assertIn("모델 C", [m.name for m in service.list_models()])
        self.assertNotIn("모델 C", [m.name for m in service.list_models(ModelFilter(speed_min=0))])

    def test_empty_maker_is_not_a_condition(self):
        self.assertEqual(len(self.service().list_models(ModelFilter(maker=""))), 3)

    def test_get_model(self):
        service = self.service()
        self.assertEqual(service.get_model(2).name, "모델 B")
        for missing in (0, 99):
            with self.assertRaises(NotFoundError):
                service.get_model(missing)

    def test_edits_to_the_file_show_up_without_restart(self):
        path = self.write_csv(SAMPLE)
        service = EquipmentModelService(path)
        self.assertEqual(len(service.list_models()), 3)
        path.write_text(SAMPLE + "제조사,모델 D,90,800,승객용,\n", encoding="utf-8")
        self.assertEqual(len(service.list_models()), 4)

    def test_display_texts(self):
        full = EquipmentModel(1, "제조사", "모델", "승객용", 105.0, 1350)
        self.assertEqual((full.speed_text, full.load_text), ("105 m/min", "1,350 kg"))
        self.assertEqual(EquipmentModel(2, "제조사", "모델", "화물용", 1.5).speed_text, "1.5 m/min")
        empty = EquipmentModel(3, "제조사", "모델", "승객용")
        self.assertEqual((empty.speed_text, empty.load_text), ("-", "-"))


if __name__ == "__main__":
    unittest.main()
