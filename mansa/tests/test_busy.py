"""로딩 레이어(ui/busy.py): 모양, 보이기/숨기기, 최소 노출 시간을 확인한다."""

import unittest
from unittest import mock

from ui import busy, theme


class LayerHtmlTest(unittest.TestCase):
    def test_shows_the_title_and_the_description(self):
        html = busy.layer_html("문서를 올리고 있어요", "잠시만 기다려 주세요")
        self.assertIn("문서를 올리고 있어요", html)
        self.assertIn("잠시만 기다려 주세요", html)

    def test_screen_readers_hear_the_message_but_not_the_decoration(self):
        html = busy.layer_html("제목", "설명")
        self.assertIn('role="status"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn('class="busy-stage" aria-hidden="true"', html)

    def test_text_is_escaped(self):
        html = busy.layer_html("<script>x</script>", "<b>y</b>")
        self.assertNotIn("<script>", html)
        self.assertNotIn("<b>y</b>", html)

    def test_one_light_runs_along_a_single_figure_eight(self):
        html = busy.layer_html("제목", "설명")
        self.assertEqual(html.count('class="track"'), 1)
        self.assertEqual(html.count('class="seg"'), busy.TAIL_LAYERS + len(busy.HEAD_GLOW))

    def test_the_line_keeps_the_same_width_from_tail_to_head(self):
        svg = busy._loop_svg()
        self.assertEqual(svg.count(f"stroke-width:{busy.STROKE};"), busy.TAIL_LAYERS)

    def test_only_the_head_gets_a_white_glow_on_top_of_the_tail(self):
        svg = busy._loop_svg()
        glow = svg[svg.index('<g class="busy-glow">'):]
        self.assertEqual(glow.count("stroke:#ffffff"), len(busy.HEAD_GLOW))
        self.assertEqual(svg.count("stroke:#ffffff"), len(busy.HEAD_GLOW))  # 꼬리 쪽에는 흰색이 없다
        self.assertEqual(svg.count("<g "), 1)

    def test_the_glow_is_subtle_and_shorter_than_the_tail(self):
        for length, width, opacity in busy.HEAD_GLOW:
            self.assertLess(length, busy.TAIL_LONGEST)
            self.assertLess(width, busy.STROKE)  # 꼬리보다 가늘어 가운데 심지로만 보인다
            self.assertLessEqual(opacity, 1)
        self.assertIn(".busy-glow", theme.build_css())

    def test_the_tail_fades_from_light_blue_through_the_brand_blue_to_violet(self):
        self.assertEqual(busy._tail_color(0), "#7dd3fc")
        self.assertEqual(busy._tail_color(0.625), "#3b5bf6")
        self.assertEqual(busy._tail_color(1), "#7c3aed")


class ComponentTest(unittest.TestCase):
    def test_the_layer_starts_hidden(self):
        layer = busy.component()
        self.assertFalse(layer.visible)
        self.assertIn(busy.LAYER_CLASS, layer.elem_classes)

    def test_show_makes_it_visible_with_the_message_and_hide_removes_it(self):
        shown = busy.show("제목", "설명")
        self.assertTrue(shown.visible)
        self.assertIn("제목", shown.value)
        self.assertFalse(busy.hide().visible)


class HoldTest(unittest.TestCase):
    def test_waits_for_the_rest_of_the_minimum_time(self):
        with mock.patch.object(busy.time, "monotonic", return_value=101.0), mock.patch.object(busy.time, "sleep") as sleep:
            busy.hold(100.0)
        sleep.assert_called_once()
        self.assertAlmostEqual(sleep.call_args.args[0], busy.MIN_SECONDS - 1.0)

    def test_does_not_wait_when_the_minimum_time_has_already_passed(self):
        with mock.patch.object(busy.time, "monotonic", return_value=200.0), mock.patch.object(busy.time, "sleep") as sleep:
            busy.hold(100.0)
        sleep.assert_not_called()

    def test_the_minimum_time_is_three_seconds(self):
        self.assertEqual(busy.MIN_SECONDS, 3)


class StyleTest(unittest.TestCase):
    def setUp(self):
        self.css = theme.build_css()

    def test_stylesheet_and_script_are_part_of_the_app(self):
        self.assertIn(".busy-layer", self.css)
        self.assertIn("busy-layer", theme.build_head())

    def test_only_the_page_content_is_covered(self):
        rule = self.css[self.css.index(".block.busy-layer {"):]
        rule = rule[:rule.index("}")]
        self.assertIn("position: absolute", rule)
        self.assertIn("inset: 0", rule)
        self.assertIn(".page {\n  position: relative;", self.css)  # 사이드바·머리글은 .page 밖이다

    def test_the_text_is_spaced_a_little_wider(self):
        title = self.css[self.css.index(".busy-title {"):]
        title = title[:title.index("}")]
        sub = self.css[self.css.index(".busy-sub {"):]
        sub = sub[:sub.index("}")]
        self.assertIn("letter-spacing: 0.05em", title)
        self.assertIn("letter-spacing: 0.03em", sub)

    def test_the_layer_stays_below_the_sticky_header_and_the_sidebar(self):
        shell = self.css[self.css.index(".block.header-block {"):]
        header_z = int(shell[shell.index("z-index:") + 8:].split(";")[0])
        rule = self.css[self.css.index(".block.busy-layer {"):]
        layer_z = int(rule[rule.index("z-index:") + 8:].split(";")[0])
        self.assertLess(layer_z, header_z)

    def test_the_box_can_follow_the_window_scroll(self):
        body = self.css[self.css.index(".busy-body {"):]
        body = body[:body.index("}")]
        self.assertNotIn("overflow: hidden", body)  # hidden 이면 sticky 가 창 스크롤을 따라가지 못한다
        self.assertIn("position: sticky", self.css[self.css.index(".busy-box {"):])

    def test_motion_is_turned_off_for_people_who_ask_for_less_motion(self):
        tail = self.css[self.css.index("prefers-reduced-motion: reduce"):]
        self.assertIn(".busy-loop .seg", tail)
        self.assertIn("animation: none", tail)

    def test_the_script_blocks_the_rest_of_the_page_while_the_layer_is_up(self):
        script = (theme.ASSETS / "busy_layer.js").read_text(encoding="utf-8")
        self.assertIn('setAttribute("inert"', script)
        self.assertIn('removeAttribute("inert"', script)


if __name__ == "__main__":
    unittest.main()
