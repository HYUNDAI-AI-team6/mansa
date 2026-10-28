"""설비 모델 목록·상세 조회. data/master/equipment_models.csv 를 읽는다.

모델 정보는 읽기 전용이고 다른 테이블이 가리키지 않아 DB 대신 파일로 둔다.
모델 ID는 파일의 줄 순서(1부터)라서, 새 모델은 파일 맨 아래에 더한다.
"""

import csv
from pathlib import Path

from features.master.errors import NotFoundError
from features.master.models import EquipmentModel, ModelFilter

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "master" / "equipment_models.csv"
REQUIRED_COLUMNS = ("maker", "name", "rated_speed", "rated_load", "usage", "drive_type")


def _number(text: str, convert, row: int, column: str):
    """빈 칸은 None, 아니면 숫자로 바꾼다. 숫자가 아니면 몇 번째 줄인지 알려 ValueError를 낸다."""
    text = text.strip()
    if not text:
        return None
    try:
        return convert(text)
    except ValueError:
        raise ValueError(f"equipment_models.csv row {row}: {column} is not a number") from None


def load_models(path: str | Path = DATA_FILE) -> list[EquipmentModel]:
    """CSV를 읽어 설비 모델 목록을 만든다. 파일 줄 순서가 모델 ID(1부터)가 된다.

    열이 모자라거나 제조사·모델명·용도가 비었거나 숫자가 아니거나
    (제조사, 모델명)이 겹치면 줄 번호와 함께 ValueError를 발생시킨다.
    """
    with Path(path).open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"equipment_models.csv: missing columns {missing}")
        rows = list(reader)
    models, seen = [], set()
    for index, row in enumerate(rows, start=1):
        maker, name, usage = [(row[c] or "").strip() for c in ("maker", "name", "usage")]
        if not (maker and name and usage):
            raise ValueError(f"equipment_models.csv row {index}: maker, name, usage are required")
        if (maker, name) in seen:
            raise ValueError(f"equipment_models.csv row {index}: duplicate model {maker} {name}")
        seen.add((maker, name))
        models.append(
            EquipmentModel(
                id=index, maker=maker, name=name, usage=usage,
                rated_speed=_number(row["rated_speed"] or "", float, index, "rated_speed"),
                rated_load=_number(row["rated_load"] or "", int, index, "rated_load"),
                drive_type=(row["drive_type"] or "").strip() or None,
            )
        )
    return models


def _in_range(value, low, high) -> bool:
    """low~high 범위에 value가 드는지 본다. 범위를 안 줬으면 항상 참, 값이 비었으면 거짓이다."""
    if low is None and high is None:
        return True
    if value is None:
        return False
    return (low is None or value >= low) and (high is None or value <= high)


def _matches(model: EquipmentModel, condition: ModelFilter) -> bool:
    """조건을 준 항목만 AND로 확인한다. 제조사가 빈 문자열이면 조건이 아니다."""
    if condition.maker and model.maker != condition.maker:
        return False
    return _in_range(model.rated_speed, condition.speed_min, condition.speed_max) and _in_range(
        model.rated_load, condition.load_min, condition.load_max
    )


class EquipmentModelService:
    """설비 모델 기준정보를 읽는다. 파일은 부를 때마다 읽어서 고치면 바로 반영된다."""

    def __init__(self, path: str | Path = DATA_FILE) -> None:
        """읽을 CSV 경로를 정한다. 지정하지 않으면 data/master/equipment_models.csv 다."""
        self._path = Path(path)

    def list_models(self, model_filter: ModelFilter | None = None) -> list[EquipmentModel]:
        """조건에 맞는 설비 모델을 파일 순서(ID 순)로 반환한다. 조건을 주지 않으면 전부다.

        제조사·정격속도·정격하중 조건을 AND로 묶는다. 속도나 하중이 비어 있는(None) 모델은
        그 값에 조건을 걸면 결과에서 빠진다. 문서 수(doc_count)는 아직 채우지 않는다.
        """
        condition = model_filter or ModelFilter()
        return [m for m in load_models(self._path) if _matches(m, condition)]

    def get_model(self, model_id: int) -> EquipmentModel:
        """모델 ID로 한 건을 조회한다. 없으면 빈 결과가 아니라 NotFoundError를 발생시킨다."""
        for model in load_models(self._path):
            if model.id == model_id:
                return model
        raise NotFoundError(f"equipment model {model_id} not found")
