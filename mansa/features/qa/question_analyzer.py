from dataclasses import replace
from typing import get_args

from core.schemas import Intent, IntentType
from features.master.equipment import EquipmentModelService
from features.master.taxonomy import TaxonomyService

# 다음 단계로 넘길 수 있는 의도. 이 밖의 값은 LLM이 지어낸 것이므로 범위 밖으로 본다.
_ALLOWED_INTENTS = frozenset(get_args(IntentType))


def _key(text: str) -> str:
    """모델 이름을 비교할 때 앞뒤 공백과 영문 대소문자 차이를 무시하는 키로 바꾼다."""
    return text.strip().casefold()


class QuestionAnalyzer:
    """질문을 읽어 Intent로 정리하는 단계. analyze(LLM)의 결과를 validate_ids로 걸러 낸다."""

    def __init__(self, models: EquipmentModelService, taxonomy: TaxonomyService) -> None:
        """등록 모델 목록과 분류표·동의어를 읽을 서비스를 받는다. 테스트에서는 가짜 객체로 바꿔 넣는다."""
        self._models = models
        self._taxonomy = taxonomy

    def validate_ids(self, intent: Intent) -> Intent:
        """Intent의 모델·부위·작업을 실제 등록된 값과 대조해 없는 값을 지운 새 Intent를 반환한다.

        모델은 등록 모델 이름과 비교하며 공백·대소문자 차이는 무시하고 등록된 이름으로 바꾼다.
        부위·작업은 동의어를 표준 태그로 바꾼 뒤 분류표에 있는 값만 남기고, 없는 작업은 None이 된다.
        허용 목록에 없는 의도는 "out_of_scope"로 바꾼다. 중복은 처음 나온 순서대로 하나만 남긴다.
        수치(values)·제목(title)은 그대로 두며 입력 intent는 바꾸지 않는다.
        설비 모델 파일을 호출할 때마다 읽는다(EquipmentModelService.list_models).
        """
        registered = {_key(model.name): model.name for model in self._models.list_models()}
        model_ids = [registered[_key(n)] for n in intent.model_ids if _key(n) in registered]

        known_parts = set(self._taxonomy.taxonomy.parts)
        parts = [p for p in map(self._taxonomy.normalize_term, intent.parts) if p in known_parts]

        task = self._taxonomy.normalize_term(intent.task) if intent.task else None
        if task not in self._taxonomy.taxonomy.tasks:
            task = None

        return replace(
            intent,
            intent=intent.intent if intent.intent in _ALLOWED_INTENTS else "out_of_scope",
            model_ids=list(dict.fromkeys(model_ids)),
            parts=list(dict.fromkeys(parts)),
            task=task,
            values=list(intent.values),
        )