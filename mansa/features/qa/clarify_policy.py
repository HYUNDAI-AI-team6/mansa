"""되묻기 판단(명세서 ClarifyPolicy). 질문이 모호할 때만 실제 후보로 선택지를 만든다."""

from core.schemas import Clarify, Intent
from features.master.taxonomy import TaxonomyService

MODEL_QUESTION = "어떤 설비 모델인가요?"
PART_QUESTION = "어느 부위 작업인가요?"
# 분류표 부위가 많아도 한 번에 보여줄 선택지는 이만큼까지다. 분류표 앞쪽부터 자른다.
MAX_PART_OPTIONS = 8

class RuleClarifyPolicy:
    """규칙으로 되묻기를 판단한다(QAService의 ClarifyPolicy 구현). LLM은 부르지 않는다.
    
    shortcut: 검색에 모델 필터가 없어 모델이 비어 있어도 되묻지 않는다, 모델 필터가 생기면 되묻기 조건에 넣는다.
    """

    def __init__(self, taxonomy: TaxonomyService) -> None:
        """부위 후보를 읽을 분류표 서비스를 받는다. 테스트에서는 가짜 객체로 바꿔 넣는다."""
        self._taxonomy = taxonomy

    def needs_clarification(self, intent: Intent) -> bool:
        """모델 후보가 둘 이상이거나 부위,작업이 모두 없으면 True다
        
        intent는 validate_ids를 거친 값이라 모델은 등록된 이름, 작업은 부위가 들어간 표준 이름이다.
        그래서 작업만 있어도 부위를 아는 것으로 본다.
        """
        return len(intent.model_ids) > 1 or not (intent.parts or intent.task)

    def build_options(self, intent: Intent) -> Clarify:
        """되묻기 질문과 선택지를 만든다. 모델이 여럿이면 그 모델들을, 아니면 분류표 부위를 선택지로 준다.

        부위 선택지는 분류표 앞쪽 MAX_PART_OPTIONS개까지만 준다.
        후보 중 하나를 추측해 고르지 않는다. 입력 intent는 바꾸지 않는다.
        """
        if len(intent.model_ids) > 1:
            return Clarify(MODEL_QUESTION, list(intent.model_ids))
        return Clarify(PART_QUESTION, list(self._taxonomy.taxonomy.parts[:MAX_PART_OPTIONS]))