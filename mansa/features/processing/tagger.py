"""청크에 부위(part)·작업(task) 태그를 붙인다.

태그는 분류표의 표준 이름만 쓴다. 질의응답이 질문에서 뽑은 부위·작업과 청크의 태그가 글자까지 같아야
순위에 반영되기 때문이다. LLM이 고른 값도 본문에 근거가 있는 표준 이름만 남긴다.
"""

import re
from dataclasses import dataclass, field

from features.master.taxonomy import TaxonomyService

# 한 글자 동의어("카")는 다른 단어의 일부("카문", "카드")에 걸리지 않게, 앞이 글자가 아니고 뒤가 조사이거나
# 글자가 아닐 때만 본문에 있다고 본다.
_PARTICLES = "이가은는을를의에도와과로"
_SHORT_FORM = r"(?<![가-힣A-Za-z0-9]){}(?:[" + _PARTICLES + r"]|(?![가-힣A-Za-z0-9]))"


def _compact(text: str) -> str:
    """공백을 모두 지우고 영문 대소문자 차이를 없앤다. PDF에서 단어 사이 공백이 달라져도 찾기 위해서다."""
    return re.sub(r"\s+", "", text).casefold()


@dataclass(frozen=True)
class Vocabulary:
    """태그로 쓸 수 있는 표준 이름과 동의어 사전. 분류표 서비스에서 읽어 만든다."""

    parts: tuple[str, ...]
    tasks: tuple[str, ...]
    synonyms: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_taxonomy(cls, service: TaxonomyService) -> "Vocabulary":
        """분류표의 부위·작업과 동의어 사전을 복사해 어휘를 만든다. 분류표는 바꾸지 않는다."""
        return cls(
            parts=tuple(service.taxonomy.parts),
            tasks=tuple(service.taxonomy.tasks),
            synonyms=dict(service.synonyms),
        )

    def forms(self, name: str) -> list[str]:
        """표준 이름이 본문에 적히는 표기들. 표준 이름 자신과 그 이름으로 바뀌는 동의어다."""
        return [name, *(word for word, standard in self.synonyms.items() if standard == name)]

    def standard(self, value: str, known: tuple[str, ...]) -> str | None:
        """value가 known의 표준 이름이면 그대로, 동의어를 바꾼 결과가 표준 이름이면 그것을, 아니면 None을 준다."""
        value = value.strip()
        if value in known:
            return value
        mapped = self.synonyms.get(value) or " ".join(self.synonyms.get(word, word) for word in value.split())
        return mapped if mapped in known else None

    def mentions(self, text: str, forms: list[str]) -> bool:
        """본문에 forms 중 하나가 적혀 있는지 본다. 공백과 영문 대소문자 차이는 무시한다."""
        compact = _compact(text)
        normalized = re.sub(r"\s+", " ", text)
        for form in forms:
            key = _compact(form)
            if not key:
                continue
            if len(key) == 1:
                if re.search(_SHORT_FORM.format(re.escape(form.strip())), normalized):
                    return True
            elif key in compact:
                return True
        return False

    def supports_part(self, text: str, part: str) -> bool:
        """부위 이름이나 그 동의어가 본문에 있으면 True다."""
        return self.mentions(text, self.forms(part))

    def supports_task(self, text: str, task: str) -> bool:
        """작업이 본문에 근거가 있으면 True다. 작업 이름의 마지막 단어(동사)와 앞부분(부위)이 모두 본문에 있어야 한다.

        "메인 로프 점검"은 본문에 "메인 로프"(또는 동의어)와 "점검"이 있을 때 근거가 있다.
        단어가 하나뿐인 작업 이름은 그 이름이 본문에 있어야 한다.
        """
        words = task.split()
        if len(words) < 2:
            return self.mentions(text, [task])
        subject = " ".join(words[:-1])
        return self.mentions(text, [words[-1]]) and self.mentions(text, self.forms(subject))
