"""기준정보 서비스가 돌려주는 데이터 클래스."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Taxonomy:
    """작업 분류표. 부위·작업·작업 위치·위험 유형 네 축의 표준 이름 목록이다."""

    parts: list[str] = field(default_factory=list)
    tasks: list[str] = field(default_factory=list)
    places: list[str] = field(default_factory=list)
    hazards: list[str] = field(default_factory=list)

    def by_axis(self) -> dict[str, list[str]]:
        """화면의 탭 이름(부위·작업·작업 위치·위험 유형)을 키로 한 목록을 반환한다."""
        return {
            "부위": self.parts, "작업": self.tasks,
            "작업 위치": self.places, "위험 유형": self.hazards,
        }


@dataclass(frozen=True)
class TaskRelation:
    """작업 하나에 이어진 작업 위치와 위험 유형. 안전 문서 검색어를 보강할 때 쓴다."""

    work: str
    places: list[str] = field(default_factory=list)
    hazards: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DepartmentInput:
    """부서 등록·수정 입력. 이름과 설명은 각각 50자 이하다(departments 테이블 컬럼 길이)."""

    name: str
    description: str = ""


@dataclass(frozen=True)
class Department:
    """departments 테이블의 부서 한 건."""

    id: int
    name: str
    description: str
    created_at: datetime | None = None


@dataclass(frozen=True)
class EquipmentModel:
    """data/master/equipment_models.csv의 설비 모델 한 건. id는 파일의 줄 순서(1부터)다. 기술 Q&A의 모델 선택 목록 원본이다.

    rated_speed는 m/min, rated_load는 kg이며 값을 모르면 None이다.
    doc_count(모델별 문서 수)는 문서 테이블이 생기기 전까지 0이다.
    """

    id: int
    maker: str
    name: str
    usage: str
    rated_speed: float | None = None
    rated_load: int | None = None
    drive_type: str | None = None
    doc_count: int = 0

    @property
    def display_id(self) -> str:
        """화면에 보여 줄 모델 ID. 예: id 1 → "M-001"."""
        return f"M-{self.id:03d}"

    @property
    def speed_text(self) -> str:
        """화면에 보여 줄 정격속도. 예: 105.0 → "105 m/min", 값이 없으면 "-"."""
        return "-" if self.rated_speed is None else f"{self.rated_speed:g} m/min"

    @property
    def load_text(self) -> str:
        """화면에 보여 줄 정격하중. 예: 750 → "750 kg", 값이 없으면 "-"."""
        return "-" if self.rated_load is None else f"{self.rated_load:,} kg"


@dataclass(frozen=True)
class ModelFilter:
    """설비 모델 목록 조건. 값을 준 조건만 적용하며 모두 AND로 묶는다. 속도는 m/min, 하중은 kg이다."""

    maker: str | None = None
    speed_min: float | None = None
    speed_max: float | None = None
    load_min: int | None = None
    load_max: int | None = None
