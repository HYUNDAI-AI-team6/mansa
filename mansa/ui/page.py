"""화면 파일들이 app.py 에 돌려주는 공통 정보."""

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class PageView:
    """메뉴로 들어올 때 화면을 다시 그리는 방법.

    app.py 는 메뉴를 누르면 reset(*reset_inputs 값) 을 불러 reset_outputs 에 넣는다.
    links 는 다른 화면으로 가는 버튼·이벤트 {이름: 컴포넌트} 로, app.py 에서 연결한다.
    """

    reset: Callable
    reset_inputs: list = field(default_factory=list)
    reset_outputs: list = field(default_factory=list)
    links: dict = field(default_factory=dict)
