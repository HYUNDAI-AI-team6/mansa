from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    """모든 테이블 모델이 상속하는 공용 기반 클래스"""