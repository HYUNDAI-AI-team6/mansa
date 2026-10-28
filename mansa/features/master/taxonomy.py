"""작업 분류표·관계표·동의어 사전을 파일에서 읽고, 동의어 변환과 검색어 보강을 한다."""

import csv
import json
from pathlib import Path
from typing import Any

from features.master.models import Taxonomy, TaskRelation

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "taxonomy"
_AXIS_KEYS = ("부위", "작업", "작업 위치", "위험 유형")


def _read_json(path: str | Path) -> Any:
    """JSON 파일을 읽는다. 파일이 없거나 형식이 틀리면 파일 이름을 담아 ValueError를 발생시킨다."""
    path = Path(path)
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path.name}: {exc}") from exc


def _string_list(value: Any, where: str) -> list[str]:
    """비어 있지 않은 문자열 목록인지 확인해 새 리스트로 반환한다. 아니면 ValueError를 발생시킨다."""
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ValueError(f"{where} must be a list of non-empty strings")
    return [v.strip() for v in value]


class TaxonomyService:
    """분류표·관계표·동의어 사전을 들고 동의어 변환(normalize_term)과 검색어 보강을 한다."""

    def __init__(
        self,
        taxonomy: Taxonomy,
        relations: dict[str, TaskRelation],
        synonyms: dict[str, str],
    ) -> None:
        """읽어 둔 데이터를 받아 서로 맞는지 확인한다.

        관계표의 작업·작업 위치·위험 유형이 분류표에 없거나, 표준 태그가 다시 동의어로 쓰이면
        오타나 연쇄 변환이 생기므로 ValueError를 발생시킨다.
        """
        for work, relation in relations.items():
            for value, known, axis in (
                (work, taxonomy.tasks, "작업"),
                *((p, taxonomy.places, "작업 위치") for p in relation.places),
                *((h, taxonomy.hazards, "위험 유형") for h in relation.hazards),
            ):
                if value not in known:
                    raise ValueError(f"relation {work!r}: {value!r} is not in taxonomy {axis}")
        chained = sorted(set(synonyms.values()) & set(synonyms))
        if chained:
            raise ValueError(f"synonym standards are also synonyms: {chained}")
        self.taxonomy = taxonomy
        self.relations = relations
        self.synonyms = synonyms

    @classmethod
    def from_directory(cls, directory: str | Path = DATA_DIR) -> "TaxonomyService":
        """폴더의 taxonomy.json, task_relations.json, synonyms.csv를 읽어 서비스를 만든다."""
        base = Path(directory)
        return cls(
            cls.load_taxonomy(base / "taxonomy.json"),
            cls.load_task_relations(base / "task_relations.json"),
            cls.load_synonyms(base / "synonyms.csv"),
        )

    @staticmethod
    def load_taxonomy(path: str | Path) -> Taxonomy:
        """작업 분류표 JSON을 읽는다. 네 축(부위·작업·작업 위치·위험 유형)이 모두 있어야 한다."""
        data = _read_json(path)
        if not isinstance(data, dict) or set(data) != set(_AXIS_KEYS):
            raise ValueError(f"taxonomy must have exactly the keys {list(_AXIS_KEYS)}")
        lists = [_string_list(data[key], f"taxonomy {key!r}") for key in _AXIS_KEYS]
        return Taxonomy(*lists)

    @staticmethod
    def load_task_relations(path: str | Path) -> dict[str, TaskRelation]:
        """작업 관계표 JSON(작업 → 작업 위치·위험 유형)을 읽어 작업 이름을 키로 한 dict로 반환한다."""
        data = _read_json(path)
        if not isinstance(data, dict):
            raise ValueError("task relations must be an object keyed by work name")
        result = {}
        for work, body in data.items():
            if not isinstance(body, dict):
                raise ValueError(f"relation {work!r} must be an object")
            places = _string_list(body.get("작업 위치"), f"relation {work!r} places")
            hazards = _string_list(body.get("위험 유형"), f"relation {work!r} hazards")
            result[work] = TaskRelation(work, places, hazards)
        return result

    @staticmethod
    def load_synonyms(path: str | Path) -> dict[str, str]:
        """동의어 사전 CSV(동의어,표준 태그)를 읽는다. 같은 동의어가 두 번 나오면 ValueError다."""
        try:
            text = Path(path).read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise ValueError(f"cannot read {Path(path).name}: {exc}") from exc
        result: dict[str, str] = {}
        for row in list(csv.reader(text.splitlines()))[1:]:
            if not row or not "".join(row).strip():
                continue
            if len(row) != 2 or not row[0].strip() or not row[1].strip():
                raise ValueError(f"bad synonym row: {row}")
            word, standard = row[0].strip(), row[1].strip()
            if word in result:
                raise ValueError(f"duplicate synonym: {word!r}")
            result[word] = standard
        return result

    def normalize_term(self, term: str) -> str:
        """동의어를 표준 태그로 바꾼다. 예: "와이어로프" → "메인 로프".

        말 전체가 사전에 있으면 그것을 쓰고, 없으면 띄어쓰기로 나눈 단어마다 바꿔 이어 붙인다.
        단어 단위로만 바꾸므로 "카드"처럼 다른 단어의 일부는 바뀌지 않는다. 사전에 없으면 그대로다.
        """
        term = term.strip()
        if term in self.synonyms:
            return self.synonyms[term]
        return " ".join(self.synonyms.get(word, word) for word in term.split())

    def expand_query_terms(self, task: str) -> list[str]:
        """작업에 이어진 작업 위치와 위험 유형을 검색어로 반환한다.

        예: "메인 로프 점검" → ["카 상부", "기계실", "추락", "끼임"]. 작업 이름이 관계표와 똑같지
        않아도 관계표의 작업 이름이 들어 있으면 쓴다(예: "메인 로프 점검하는 법"). 여러 개가 맞으면
        가장 긴 이름을 고른다. 관계표에 없는 작업이면 빈 리스트를 반환한다.
        """
        candidates = [task.strip(), self.normalize_term(task)]
        names = sorted(self.relations, key=len, reverse=True)
        found = next((n for n in names if n in candidates), None)
        found = found or next((n for n in names if any(n in c for c in candidates)), None)
        if found is None:
            return []
        relation = self.relations[found]
        return list(dict.fromkeys([*relation.places, *relation.hazards]))
