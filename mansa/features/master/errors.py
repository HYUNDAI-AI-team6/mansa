"""기준정보 서비스가 화면에 알려 주는 오류. 공통 core/exceptions.py가 정리되면 그쪽으로 옮긴다."""


class ValidationError(ValueError):
    """입력이 비었거나 너무 길 때 발생한다. 메시지는 사용자에게 보여도 된다."""


class DuplicateError(ValueError):
    """같은 이름이 이미 등록되어 있을 때 발생한다."""


class NotFoundError(LookupError):
    """찾는 항목이 없을 때 발생한다. 빈 목록과 구분하려고 따로 둔다."""
