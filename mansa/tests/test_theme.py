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


class DropHoverTest(unittest.TestCase):
    def test_head_carries_the_drag_over_script_as_its_own_tag(self):
        head = theme.build_head()
        self.assertEqual(head.count("<script>"), 2)
        self.assertIn('".drop-wrap"', head)
        self.assertIn("dragover", head)

    def test_only_file_drags_highlight_the_zone(self):
        script = (theme.ASSETS / "drop_hover.js").read_text(encoding="utf-8")
        self.assertIn('includes("Files")', script)


class BuildCssTest(unittest.TestCase):
    def test_includes_every_stylesheet(self):
        css = theme.build_css()
        for marker in ("login-drift-a", "버튼 호버", ".chat-input"):
            self.assertIn(marker, css)

    def test_buttons_get_darker_on_hover_instead_of_lifting(self):
        css = theme.build_css()
        self.assertNotIn("translateY(-1px)", css)
        for rule in ("button.btn-primary:not(:disabled):hover", "button.btn-primary:not(:disabled):active",
                     "button.btn-secondary:not(:disabled):hover", "button.soft-btn:not(:disabled):hover"):
            self.assertIn(rule, css)

    def test_inputs_and_dropdowns_get_a_blue_border_while_active(self):
        css = theme.build_css()
        for rule in (".field input:focus", ".search input:focus", ".select .wrap:focus-within",
                     ".model-select .wrap:focus-within", ".chat-input:focus-within",
                     ".question-box:focus-within", ".admin-card .field input:focus"):
            self.assertIn(rule, css)

    def test_type_card_hover_changes_only_the_border(self):
        css = theme.build_css()
        self.assertIn(".type-card:hover {\n  border-color: var(--brand);\n}", css)
        self.assertNotIn(".type-card:hover b", css)

    def test_the_failure_tooltip_shows_on_hover_only_and_is_translucent(self):
        css = theme.build_css()
        self.assertIn(".fail-info:hover .fail-tip", css)
        self.assertIn(".fail-tip > span:empty", css)
        self.assertNotIn(".fail-info:focus", css)
        tip = css[css.index(".fail-tip {"):]
        self.assertIn("rgba(26, 29, 35, 0.82)", tip.split("}")[0])

    def test_pill_choices_turn_blue_on_hover(self):
        css = theme.build_css()
        self.assertIn(".chip-radio label:not(.selected):not(:has(input:checked)):hover", css)
        self.assertIn(".chip-radio label:has(input:checked):hover", css)

    def test_drag_over_and_type_card_hover_rules_exist(self):
        css = theme.build_css()
        for rule in (".drop-wrap.dragover .dropzone", ".type-card:hover", ".type-card.on:hover"):
            self.assertIn(rule, css)


if __name__ == "__main__":
    unittest.main()
