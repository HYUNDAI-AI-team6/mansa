import unittest

from ui import theme


class BuildHeadTest(unittest.TestCase):
    def test_wraps_the_chat_key_script_in_a_script_tag(self):
        head = theme.build_head()
        self.assertTrue(head.startswith("<script>") and head.endswith("</script>"))
        self.assertIn("keypress", head)  # Gradio 입력칸은 엔터를 keypress 로 받는다

    def test_script_only_touches_the_chat_inputs(self):
        self.assertIn(".q-text textarea", theme.build_head())
        self.assertIn(".chat-text textarea", theme.build_head())


class BuildCssTest(unittest.TestCase):
    def test_includes_every_stylesheet(self):
        css = theme.build_css()
        for marker in ("login-drift-a", "버튼 호버", ".chat-input"):
            self.assertIn(marker, css)


if __name__ == "__main__":
    unittest.main()
