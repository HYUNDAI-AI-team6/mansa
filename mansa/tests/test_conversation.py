import os
import unittest

from sqlalchemy import create_engine, delete
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from core.models.conversation import Conversation

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


class ConversationModelTest(unittest.TestCase):
    def test_compiles_for_mysql(self):
        # MySQL은 VARCHAR 길이가 없으면 여기서 에러가 난다
        ddl = str(CreateTable(Conversation.__table__).compile(dialect=mysql.dialect()))
        self.assertIn("CREATE TABLE conversation", ddl)


@unittest.skipUnless(TEST_DATABASE_URL, "set TEST_DATABASE_URL to run DB tests")
class ConversationDbTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(TEST_DATABASE_URL)
        Conversation.__table__.create(self.engine, checkfirst=True)  # 없을 때만 만든다
        self.saved_id = None

    def tearDown(self):
        if self.saved_id is not None:  # 이 테스트가 넣은 행만 지운다
            with Session(self.engine) as session:
                session.execute(delete(Conversation).where(Conversation.id == self.saved_id))
                session.commit()
        self.engine.dispose()

    def test_save_and_load(self):
        with Session(self.engine) as session:
            conversation = Conversation(user_id=1, title="브레이크 점검")
            session.add(conversation)
            session.commit()
            self.saved_id = conversation.id

        with Session(self.engine) as session:  # 새 세션으로 DB에서 다시 읽는다
            loaded = session.get(Conversation, self.saved_id)

        self.assertEqual(loaded.user_id, 1)
        self.assertEqual(loaded.title, "브레이크 점검")
        self.assertIsNotNone(loaded.created_at)  # DB가 생성일을 자동으로 채웠다


if __name__ == "__main__":
    unittest.main()