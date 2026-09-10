from __future__ import annotations

import html
import os
from pathlib import Path
import re
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import ASSETS_DIR
from app.markdown import _extract_math, to_html


class MarkdownTests(unittest.TestCase):
    def test_bundled_katex_runtime_and_all_woff2_fonts_are_present(self) -> None:
        katex_dir = ASSETS_DIR / "vendor" / "katex"
        stylesheet = katex_dir / "katex.min.css"
        self.assertTrue((katex_dir / "katex.min.js").is_file())
        self.assertTrue(stylesheet.is_file())
        self.assertTrue((katex_dir / "LICENSE").is_file())

        css = stylesheet.read_text(encoding="utf-8")
        font_paths = {
            Path(path)
            for path in re.findall(r"url\((fonts/[^)]+\.woff2)\)", css)
        }
        self.assertGreaterEqual(len(font_paths), 20)
        self.assertEqual(
            [
                path.as_posix()
                for path in sorted(font_paths)
                if not (katex_dir / path).is_file()
            ],
            [],
        )

    def test_renders_common_inline_and_display_delimiters_as_vector_placeholders(
        self,
    ) -> None:
        rendered = to_html(
            r"集合 \(\Theta\) 与 $x^2$。"
            "\n\n"
            r"\[m(\varnothing)=0,\qquad \sum_{X\subseteq\Theta}m(X)=1\]"
        )
        self.assertEqual(rendered.count("data-tex="), 3)
        self.assertEqual(rendered.count('class="math-inline"'), 2)
        self.assertEqual(rendered.count('class="math-display"'), 1)
        self.assertNotIn("data:image", rendered)
        self.assertNotIn("<img", rendered)
        self.assertNotIn("<canvas", rendered)

    def test_preserves_multiline_aligned_formula_as_one_display_expression(self) -> None:
        rendered = to_html(
            r"$$\begin{aligned}a &= b + c \\ d &= e - f\end{aligned}$$"
        )
        self.assertEqual(rendered.count("data-tex="), 1)
        self.assertEqual(rendered.count('class="math-display"'), 1)
        self.assertIn(r"\begin{aligned}", html.unescape(rendered))
        self.assertIn(r"a &= b + c \\ d &= e - f", html.unescape(rendered))

    def test_preserves_matrix_cases_and_column_separators(self) -> None:
        rendered = to_html(
            r"\[A=\begin{pmatrix}a&b\\c&d\end{pmatrix},\quad "
            r"f(x)=\begin{cases}x^2,&x\ge0\\-x,&x<0\end{cases}\]"
        )
        decoded = html.unescape(rendered)
        self.assertEqual(rendered.count("data-tex="), 1)
        self.assertIn(r"\begin{pmatrix}a&b\\c&d\end{pmatrix}", decoded)
        self.assertIn(r"\begin{cases}x^2,&x\ge0\\-x,&x<0\end{cases}", decoded)

    def test_recognizes_and_normalizes_bare_display_environments(self) -> None:
        source, formulas = _extract_math(
            "推导如下：\n"
            r"\begin{align}a &= b\\c &= d\end{align}"
            "\n然后：\n"
            r"\begin{equation}E=mc^2\label{mass}\end{equation}"
        )
        self.assertEqual(len(formulas), 2)
        self.assertNotIn(r"\begin", source)
        self.assertEqual(
            formulas[0][1],
            r"\begin{aligned}a &= b\\c &= d\end{aligned}",
        )
        self.assertEqual(formulas[1][1], r"E=mc^2")
        self.assertTrue(all(display for _, _, display in formulas))

    def test_does_not_render_math_delimiters_inside_code(self) -> None:
        rendered = to_html(
            "`$inline_code$`\n\n"
            "```text\n"
            "\\[not_a_formula\\]\n"
            "```"
        )
        self.assertNotIn("data-tex=", rendered)
        self.assertIn("$inline_code$", rendered)
        self.assertIn("not_a_formula", rendered)

    def test_renders_inline_code_and_copyable_fenced_code_block(self) -> None:
        rendered = to_html(
            "调用 `build_chat_body()`，然后执行：\n\n"
            "```python\n"
            "payload = {'model': 'deepseek-flash'}\n"
            "print(payload)\n"
            "```"
        )
        self.assertIn("<code>build_chat_body()</code>", rendered)
        self.assertIn('data-code-block="true"', rendered)
        self.assertIn('class="code-toolbar"', rendered)
        self.assertIn('class="code-language">Python</span>', rendered)
        self.assertIn('class="code-copy"', rendered)
        self.assertIn("payload = {'model': 'deepseek-flash'}", rendered)
        self.assertIn("overflow-x:auto", rendered)

    def test_unclosed_streaming_formula_stays_as_text(self) -> None:
        rendered = to_html(r"生成中：\[\sum_{i=1}^{n}")
        self.assertNotIn("data-tex=", rendered)
        self.assertIn(r"\sum", rendered)

    def test_formula_source_is_html_escaped_and_cannot_inject_markup(self) -> None:
        rendered = to_html(r'$x"><script>window.bad=true</script>$')
        self.assertEqual(rendered.count("data-tex="), 1)
        self.assertNotIn("<script>window.bad", rendered)
        self.assertIn("&lt;script&gt;", rendered)

    def test_invalid_math_is_left_for_safe_katex_error_rendering(self) -> None:
        rendered = to_html(r"前文 $\definitelyUnknownCommand{x}$ 后文")
        self.assertIn('data-tex="\\definitelyUnknownCommand{x}"', rendered)
        self.assertIn("前文", rendered)
        self.assertIn("后文", rendered)
        self.assertIn(".katex-error", rendered)

    def test_long_formulas_have_dedicated_overflow_container(self) -> None:
        rendered = to_html(r"\[" + " + ".join(f"x_{{{i}}}" for i in range(80)) + r"\]")
        self.assertIn('class="math-display-shell"', rendered)
        self.assertIn("overflow-x:auto", rendered)
        self.assertIn("is-overflowing", rendered)
        self.assertIn("scrollbar", rendered)

    def test_dark_formula_markup_uses_dark_palette_without_raster_resources(self) -> None:
        rendered = to_html(r"\[x^2+y^2=z^2\]", dark=True)
        self.assertIn("#F2F2F2", rendered)
        self.assertIn("#242424", rendered)
        self.assertNotRegex(rendered, re.compile(r"data:image|<img|<canvas", re.I))


if __name__ == "__main__":
    unittest.main()
