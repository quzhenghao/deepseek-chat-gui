from __future__ import annotations

import html
import re
import sys

from markdown_it import MarkdownIt

if sys.platform == "darwin":
    _CODE_FONT_STACK = "Menlo, Monaco"
elif sys.platform == "win32":
    _CODE_FONT_STACK = "Consolas, Courier New, monospace"
else:
    _CODE_FONT_STACK = "DejaVu Sans Mono, Liberation Mono, monospace"


_MARKDOWN = MarkdownIt("commonmark", {"breaks": True, "html": False}).enable("table")
_MATH_TOKEN_PREFIX = "DEEPSEEKFORMULATOKEN"
_CODE_BLOCK_RE = re.compile(
    r"<pre><code(?: class=\"language-([^\"]+)\")?>(.*?)</code></pre>",
    flags=re.DOTALL,
)
_LANGUAGE_LABELS = {
    "bash": "Bash",
    "c": "C",
    "cpp": "C++",
    "css": "CSS",
    "go": "Go",
    "html": "HTML",
    "java": "Java",
    "javascript": "JavaScript",
    "js": "JavaScript",
    "json": "JSON",
    "markdown": "Markdown",
    "md": "Markdown",
    "python": "Python",
    "py": "Python",
    "rust": "Rust",
    "shell": "Shell",
    "sql": "SQL",
    "swift": "Swift",
    "text": "Text",
    "toml": "TOML",
    "tsx": "TSX",
    "typescript": "TypeScript",
    "ts": "TypeScript",
    "xml": "XML",
    "yaml": "YAML",
    "yml": "YAML",
}

_BARE_DISPLAY_ENVIRONMENTS = (
    "equation",
    "equation*",
    "displaymath",
    "align",
    "align*",
    "alignat",
    "alignat*",
    "flalign",
    "flalign*",
    "gather",
    "gather*",
    "multline",
    "multline*",
    "aligned",
    "alignedat",
    "gathered",
    "split",
    "cases",
    "matrix",
    "pmatrix",
    "bmatrix",
    "Bmatrix",
    "vmatrix",
    "Vmatrix",
    "smallmatrix",
    "array",
)
_BARE_DISPLAY_BEGIN_RE = re.compile(
    rf"\\begin\{{({'|'.join(re.escape(name) for name in _BARE_DISPLAY_ENVIRONMENTS)})\}}"
)


def _is_escaped(text: str, position: int) -> bool:
    slashes = 0
    position -= 1
    while position >= 0 and text[position] == "\\":
        slashes += 1
        position -= 1
    return slashes % 2 == 1


def _find_unescaped(
    text: str,
    delimiter: str,
    start: int,
    *,
    stop_at_newline: bool = False,
) -> int:
    position = start
    while True:
        position = text.find(delimiter, position)
        if position < 0:
            return -1
        if stop_at_newline and "\n" in text[start:position]:
            return -1
        if not _is_escaped(text, position):
            return position
        position += len(delimiter)


def _fence_marker(line: str) -> tuple[str, int] | None:
    match = re.match(r" {0,3}(`{3,}|~{3,})", line)
    if not match:
        return None
    marker = match.group(1)
    return marker[0], len(marker)


def _closing_fence(line: str, marker: tuple[str, int]) -> bool:
    character, minimum = marker
    return bool(re.match(rf" {{0,3}}{re.escape(character)}{{{minimum},}}\s*$", line))


def _inline_dollar_end(text: str, start: int) -> int:
    """Find a conservative CommonMark-friendly closing inline dollar."""

    if start + 1 >= len(text) or text[start + 1].isspace():
        return -1
    position = start + 1
    while True:
        position = text.find("$", position)
        if position < 0 or "\n" in text[start + 1 : position]:
            return -1
        if _is_escaped(text, position):
            position += 1
            continue
        if position + 1 < len(text) and text[position + 1] == "$":
            position += 2
            continue
        if position > start + 1 and not text[position - 1].isspace():
            return position
        position += 1


def _normalize_math(expression: str, display: bool) -> str:
    """Normalize outer document environments without flattening their layout."""

    normalized = expression.strip()
    if not display:
        return normalized

    replacements = {
        "equation": None,
        "equation*": None,
        "displaymath": None,
        "align": "aligned",
        "align*": "aligned",
        "alignat": "alignedat",
        "alignat*": "alignedat",
        "flalign": "aligned",
        "flalign*": "aligned",
        "gather": "gathered",
        "gather*": "gathered",
        "multline": "gathered",
        "multline*": "gathered",
    }
    for environment, replacement in replacements.items():
        opening = rf"\begin{{{environment}}}"
        closing = rf"\end{{{environment}}}"
        if normalized.startswith(opening) and normalized.endswith(closing):
            body = normalized[len(opening) : -len(closing)].strip()
            if replacement is None:
                normalized = body
            else:
                normalized = rf"\begin{{{replacement}}}{body}\end{{{replacement}}}"
            break

    return re.sub(r"\\label\{[^{}]*\}", "", normalized)


def _extract_math(text: str) -> tuple[str, list[tuple[str, str, bool]]]:
    """Replace formulas outside Markdown code spans/fences with safe tokens."""

    if "$" not in text and "\\" not in text:
        # No dollar sign and no backslash means no math delimiter can appear,
        # so the character-by-character scan can be skipped entirely.
        return text, []

    output: list[str] = []
    formulas: list[tuple[str, str, bool]] = []
    fence: tuple[str, int] | None = None
    position = 0

    def add_formula(expression: str, display: bool) -> None:
        expression = _normalize_math(expression, display)
        if not expression:
            return
        token = f"{_MATH_TOKEN_PREFIX}{len(formulas):04d}END"
        formulas.append((token, expression, display))
        output.append(f"\n\n{token}\n\n" if display else token)

    while position < len(text):
        if position == 0 or text[position - 1] == "\n":
            line_end = text.find("\n", position)
            if line_end < 0:
                line_end = len(text)
            line = text[position:line_end]
            marker = _fence_marker(line)
            if fence is not None:
                if marker and marker[0] == fence[0] and _closing_fence(line, fence):
                    fence = None
                output.append(text[position : min(len(text), line_end + 1)])
                position = min(len(text), line_end + 1)
                continue
            if marker is not None:
                fence = marker
                output.append(text[position : min(len(text), line_end + 1)])
                position = min(len(text), line_end + 1)
                continue

        if text[position] == "`":
            run_end = position + 1
            while run_end < len(text) and text[run_end] == "`":
                run_end += 1
            delimiter = text[position:run_end]
            closing = text.find(delimiter, run_end)
            if closing < 0:
                output.append(text[position:])
                break
            closing += len(delimiter)
            output.append(text[position:closing])
            position = closing
            continue

        if text.startswith(r"\[", position) and not _is_escaped(text, position):
            closing = _find_unescaped(text, r"\]", position + 2)
            if closing >= 0:
                add_formula(text[position + 2 : closing], True)
                position = closing + 2
                continue

        if text.startswith("$$", position) and not _is_escaped(text, position):
            closing = _find_unescaped(text, "$$", position + 2)
            if closing >= 0:
                add_formula(text[position + 2 : closing], True)
                position = closing + 2
                continue

        if text.startswith(r"\(", position) and not _is_escaped(text, position):
            closing = _find_unescaped(
                text,
                r"\)",
                position + 2,
                stop_at_newline=True,
            )
            if closing >= 0:
                add_formula(text[position + 2 : closing], False)
                position = closing + 2
                continue

        if text[position] == "$" and not _is_escaped(text, position):
            if position + 1 < len(text) and text[position + 1] != "$":
                closing = _inline_dollar_end(text, position)
                if closing >= 0:
                    add_formula(text[position + 1 : closing], False)
                    position = closing + 1
                    continue

        if text.startswith(r"\begin{", position) and not _is_escaped(text, position):
            match = _BARE_DISPLAY_BEGIN_RE.match(text, position)
            if match:
                environment = match.group(1)
                delimiter = rf"\end{{{environment}}}"
                closing = _find_unescaped(text, delimiter, match.end())
                if closing >= 0:
                    end = closing + len(delimiter)
                    add_formula(text[position:end], True)
                    position = end
                    continue

        output.append(text[position])
        position += 1

    return "".join(output), formulas


def _formula_html(expression: str, display: bool) -> str:
    attribute = html.escape(expression, quote=True)
    readable = html.escape(expression)
    if display:
        return (
            '<div class="math-display-shell" '
            'aria-label="数学公式，可横向滚动查看完整内容">'
            f'<div class="math-display" data-tex="{attribute}" data-display="true">'
            f'<code class="math-source">\\[{readable}\\]</code>'
            "</div></div>"
        )
    return (
        f'<span class="math-inline" data-tex="{attribute}" data-display="false" '
        f'aria-label="{attribute}"><code class="math-source">\\({readable}\\)</code>'
        "</span>"
    )


def _code_language_label(language: str | None) -> str:
    normalized = str(language or "").strip().lower()
    return _LANGUAGE_LABELS.get(normalized, normalized or "Code")


def _decorate_code_blocks(rendered: str) -> str:
    """Add a copy affordance while retaining Markdown's escaped code source."""

    def replace(match: re.Match[str]) -> str:
        language = match.group(1) or ""
        body = match.group(2)
        label = html.escape(_code_language_label(language))
        class_attribute = (
            f' class="language-{html.escape(language, quote=True)}"'
            if language
            else ""
        )
        return (
            '<div class="code-block" data-code-block="true">'
            '<div class="code-toolbar">'
            f'<span class="code-language">{label}</span>'
            '<button class="code-copy" type="button" aria-label="复制代码">'
            "复制"
            "</button>"
            "</div>"
            f"<pre><code{class_attribute}>{body}</code></pre>"
            "</div>"
        )

    return _CODE_BLOCK_RE.sub(replace, rendered)


def _style_html(dark: bool) -> str:
    """Return the shared stylesheet of every rendered Markdown body."""

    foreground = "#F2F2F2" if dark else "#171717"
    secondary = "#B7B7B7" if dark else "#5E5E5E"
    code_background = "#151515" if dark else "#F4F4F4"
    border = "#3A3A3A" if dark else "#E3E3E3"
    scroll_track = "#242424" if dark else "#EEEEEE"
    scroll_thumb = "#858585" if dark else "#8F8F8F"
    error = "#FF8A8A" if dark else "#B42318"

    return f"""
    <style>
      .markdown-body {{ color:{foreground}; font-size:14px; line-height:1.65;
        overflow-wrap:anywhere; word-break:normal; }}
      .markdown-body p {{ margin:0 0 10px 0; }}
      .markdown-body p:last-child {{ margin-bottom:0; }}
      .markdown-body h1, .markdown-body h2, .markdown-body h3 {{
        margin:14px 0 8px 0; color:{foreground}; }}
      .markdown-body h1 {{ font-size:21px; }}
      .markdown-body h2 {{ font-size:18px; }}
      .markdown-body h3 {{ font-size:16px; }}
      .markdown-body ul, .markdown-body ol {{
        margin:4px 0 10px 0; padding-left:22px; }}
      .markdown-body li {{ margin:3px 0; }}
      .markdown-body blockquote {{ color:{secondary}; border-left:3px solid {border};
        margin:8px 0; padding-left:12px; }}
      .markdown-body .code-block {{ margin:10px 0 12px 0; border:1px solid {border};
        border-radius:10px; overflow:hidden; background:{code_background}; }}
      .markdown-body .code-toolbar {{ display:flex; align-items:center; min-height:30px;
        box-sizing:border-box; padding:4px 8px 4px 12px; border-bottom:1px solid {border};
        background:{code_background}; }}
      .markdown-body .code-language {{ flex:1; color:{secondary}; font-size:11px;
        font-family:{_CODE_FONT_STACK}; text-transform:none; }}
      .markdown-body .code-copy {{ flex:none; color:{secondary}; background:transparent;
        border:1px solid transparent; border-radius:6px; padding:3px 8px; font-size:11px;
        cursor:pointer; }}
      .markdown-body .code-copy:hover {{ color:{foreground}; background:{border}; }}
      .markdown-body .code-copy.is-copied {{ color:{foreground}; background:{border}; }}
      .markdown-body pre {{ margin:0; padding:12px 14px; background:{code_background};
        white-space:pre; overflow-x:auto; overflow-y:hidden; }}
      .markdown-body pre code {{ display:block; font-family:{_CODE_FONT_STACK};
        color:{foreground}; background:transparent; line-height:1.55; font-size:13px; }}
      .markdown-body :not(pre) > code:not(.math-source) {{
        font-family:{_CODE_FONT_STACK};
        color:{foreground}; background:{code_background}; border:1px solid {border};
        border-radius:5px; padding:1px 5px; font-size:.92em; white-space:pre-wrap; }}
      .markdown-body table {{ border-collapse:collapse; margin:8px 0 12px 0;
        display:block; max-width:100%; overflow-x:auto; }}
      .markdown-body th, .markdown-body td {{
        border:1px solid {border}; padding:6px 9px; }}
      .markdown-body a {{ color:{foreground}; text-decoration:underline; }}
      .markdown-body hr {{ border:none; border-top:1px solid {border}; }}
      .markdown-body .math-inline {{ display:inline-block; max-width:100%;
        overflow:visible; vertical-align:-0.18em;
        line-height:normal; margin:0 0.08em; }}
      .markdown-body .math-inline.is-overflowing {{
        overflow-x:auto; overflow-y:hidden; }}
      .markdown-body .math-inline.is-overflowing::-webkit-scrollbar {{ height:5px; }}
      .markdown-body .math-display-shell {{ position:relative; box-sizing:border-box;
        width:100%; max-width:100%; margin:11px 0 13px 0; padding:3px 0 5px;
        overflow-x:auto; overflow-y:hidden; overscroll-behavior-x:contain; }}
      .markdown-body .math-display-shell.is-overflowing {{
        box-shadow:inset -12px 0 10px -12px {scroll_thumb}; }}
      .markdown-body .math-display-shell::-webkit-scrollbar {{ height:8px; }}
      .markdown-body .math-display-shell::-webkit-scrollbar-track,
      .markdown-body .math-inline.is-overflowing::-webkit-scrollbar-track {{
        background:{scroll_track}; border-radius:4px; }}
      .markdown-body .math-display-shell::-webkit-scrollbar-thumb,
      .markdown-body .math-inline.is-overflowing::-webkit-scrollbar-thumb {{
        background:{scroll_thumb}; border-radius:4px; }}
      .markdown-body .math-display-shell .katex-display {{
        box-sizing:border-box; min-width:max-content; margin:0;
        padding:3px 12px 6px; text-align:center; }}
      .markdown-body .math-inline .katex {{ font-size:1.07em; }}
      .markdown-body .math-display .katex {{ font-size:1.12em; }}
      .markdown-body .math-source {{ color:{secondary}; background:transparent;
        white-space:pre-wrap; overflow-wrap:anywhere; padding:2px 4px; }}
      .markdown-body .katex-error {{ color:{error} !important;
        font-family:{_CODE_FONT_STACK}; }}
    </style>"""


def render_body(text: str) -> str:
    """Render Markdown into the inner HTML of a ``.markdown-body`` block."""

    source, formulas = _extract_math(text or "")
    rendered = _MARKDOWN.render(source) if source else ""
    rendered = _decorate_code_blocks(rendered)
    for token, expression, display in formulas:
        formula = _formula_html(expression, display)
        if display:
            rendered = rendered.replace(f"<p>{token}</p>", formula)
        rendered = rendered.replace(token, formula)

    return rendered or html.escape(text or "")


def to_html(text: str, dark: bool = False) -> str:
    """Render Markdown to a safe fragment containing KaTeX formula placeholders."""

    return (
        _style_html(dark)
        + f'\n    <div class="markdown-body">{render_body(text)}</div>\n    '
    )


def _tail_starts_open_fence(source: str) -> bool:
    """True when the streaming tail is one code fence that is still open."""

    lines = source.split("\n")
    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index >= len(lines):
        return False
    marker = _fence_marker(lines[index])
    if marker is None:
        return False
    for line in lines[index + 1 :]:
        if _closing_fence(line, marker):
            return False
    return True


def _leading_fence_marker(source: str) -> tuple[str, int] | None:
    """Fence marker of the first non-blank line, when it opens a fence."""

    for line in source.split("\n"):
        if not line.strip():
            continue
        return _fence_marker(line)
    return None


# Rendered code blocks grow by appending raw text to the ``<code>`` element,
# so the frozen HTML keeps a hole where that text has to land.
_CODE_PLACEHOLDER = "DEEPSEEKSTREAMCODEPLACEHOLDER"


def _stable_prefix_length(tail: str) -> int:
    """Length of the tail prefix whose blocks can never change again.

    Markdown parses blocks top-down, so a chunk of new text can only modify
    the block it lands in; every complete block before that one is final.
    The last top-level block is therefore kept unstable, and the returned
    length always sits on a top-level block boundary, which makes rendering
    the frozen prefix on its own byte-for-byte identical to rendering it
    together with the rest of the document.
    """

    if not tail.strip():
        return 0
    if _tail_starts_open_fence(tail):
        return 0
    starts: list[int] = []
    for token in _MARKDOWN.parse(tail):
        if token.level == 0 and token.map:
            starts.append(int(token.map[0]))
    if len(starts) < 2:
        return 0
    boundary_line = starts[-1]
    if boundary_line <= 0:
        return 0
    return sum(len(line) + 1 for line in tail.split("\n")[:boundary_line])


class StreamingMarkdown:
    """Incremental Markdown renderer for a growing streaming answer.

    The renderer keeps two DOM-ready pieces: ``stable_html`` grows by appending
    the HTML of completed blocks, and ``tail_html`` is re-rendered from the
    last block on every update.  The model output can therefore stream into a
    display surface without ever re-parsing or re-rendering the whole answer.

    An open code fence is handled line by line: finished lines are appended to
    the code element already on screen (``code`` deltas) instead of re-rendering
    the whole block, which keeps every update proportional to the new text.
    """

    def __init__(self, dark: bool = False) -> None:
        self._dark = bool(dark)
        self._source = ""
        self._stable_source_length = 0
        self._stable_html = ""
        self._tail_html = ""
        self._code_text = ""
        self._code_tail = ""
        self._code_insert_at = 0
        self._code_open = False
        self._code_marker: tuple[str, int] | None = None
        self._revision = 0

    @property
    def dark(self) -> bool:
        return self._dark

    @property
    def source(self) -> str:
        return self._source

    @property
    def stable_html(self) -> str:
        return self.composed_stable_html()

    @property
    def raw_stable_html(self) -> str:
        return self._stable_html

    @property
    def code_tail_text(self) -> str:
        """Live last line of an open code fence, as it has to be displayed."""

        return self._displayed_code_tail()

    def _displayed_code_tail(self) -> str:
        # Markdown drops a trailing whitespace-only line of a code block.  It
        # is still carried verbatim, because indentation that arrives later
        # must keep it.
        return self._code_tail if self._code_tail.strip() else ""

    @property
    def tail_html(self) -> str:
        return self._tail_html

    @property
    def revision(self) -> int:
        return self._revision

    def set_theme(self, dark: bool) -> None:
        self._dark = bool(dark)

    def reset(self) -> None:
        self._source = ""
        self._stable_source_length = 0
        self._stable_html = ""
        self._tail_html = ""
        self._code_text = ""
        self._code_tail = ""
        self._code_insert_at = 0
        self._code_open = False
        self._code_marker = None
        self._revision += 1

    def composed_stable_html(self, include_code_tail: bool = True) -> str:
        """Frozen HTML including the code lines appended since it was drawn."""

        code = self._code_text
        if include_code_tail:
            code += self._displayed_code_tail()
        if not code:
            return self._stable_html
        at = max(0, min(self._code_insert_at, len(self._stable_html)))
        return (
            self._stable_html[:at]
            + html.escape(code)
            + self._stable_html[at:]
        )

    def style_html(self) -> str:
        return _style_html(self._dark)

    def body_html(self) -> str:
        return (
            '<div class="markdown-body">'
            f"{self.composed_stable_html()}{self._tail_html}"
            "</div>"
        )

    def html(self) -> str:
        return self.style_html() + self.body_html()

    def update(self, source: str) -> tuple[str, str, str]:
        """Grow the renderer: ``(stable delta, code delta, tail)`` HTML."""

        source = str(source or "")
        if source == self._source:
            return "", "", self._tail_html
        if not source.startswith(self._source):
            self.reset()
        self._source = source
        self._revision += 1

        html_delta = ""
        code_delta = ""
        for _ in range(8):
            tail_source = source[self._stable_source_length :]
            html, code, remaining = self._freeze(tail_source)
            if html:
                html_delta += html
                self._stable_html += html
            if code:
                code_delta += code
                self._code_text += code
            consumed = len(tail_source) - len(remaining)
            if consumed > 0:
                self._stable_source_length += consumed
            if consumed <= 0 or (not html and not code):
                break
        remaining_source = source[self._stable_source_length :]
        self._tail_html = (
            render_body(remaining_source) if remaining_source.strip() else ""
        )
        return html_delta, code_delta, self._tail_html

    def _freeze(self, tail: str) -> tuple[str, str, str]:
        """Freeze what is final and return ``(html, code, remaining tail)``."""

        if not tail:
            return "", "", tail
        if self._code_open:
            return self._freeze_open_fence(tail)
        marker = _leading_fence_marker(tail)
        if marker is None:
            length = _stable_prefix_length(tail)
            if length <= 0:
                return "", "", tail
            return render_body(tail[:length]), "", tail[length:]
        return self._freeze_new_fence(tail, marker)

    def _freeze_new_fence(
        self,
        tail: str,
        marker: tuple[str, int],
    ) -> tuple[str, str, str]:
        lines = tail.split("\n")
        closing = next(
            (
                index
                for index in range(1, len(lines))
                if _closing_fence(lines[index], marker)
            ),
            None,
        )
        if closing is None:
            complete = lines[:-1]
            if not complete:
                return "", "", tail
            html = self._start_code_block("\n".join(complete) + "\n", marker)
            self._code_tail = lines[-1]
            return html, "", ""
        remaining = "\n".join(lines[closing + 1 :])
        head = "\n".join(lines[: closing + 1]) + "\n"
        self._code_tail = ""
        return render_body(head), "", remaining

    def _start_code_block(
        self,
        markup: str,
        marker: tuple[str, int] | None = None,
    ) -> str:
        """Render the head of a fence and remember where code lines go."""

        rendered = render_body(markup + _CODE_PLACEHOLDER)
        index = rendered.find(_CODE_PLACEHOLDER)
        self._code_open = True
        self._code_marker = marker
        if index < 0:
            self._code_insert_at = len(self._stable_html)
            return rendered
        self._code_insert_at = len(self._stable_html) + index
        return rendered[:index] + rendered[index + len(_CODE_PLACEHOLDER) :]

    def _freeze_open_fence(self, tail: str) -> tuple[str, str, str]:
        # The first fragment continues the line that is still being typed, so
        # it is prepended before the closing marker of the fence is looked for.
        lines = tail.split("\n")
        if self._code_tail:
            lines = [self._code_tail + lines[0], *lines[1:]]
        marker = self._code_marker
        for index in range(0, len(lines) - 1):
            if marker is not None and _closing_fence(lines[index], marker):
                code = "\n".join(lines[:index]) + "\n" if index else ""
                remaining = "\n".join(lines[index + 1 :])
                self._code_open = False
                self._code_tail = ""
                return "", code, remaining
        complete = lines[:-1]
        if marker is not None and _closing_fence(lines[-1], marker):
            # A closing marker does not need its own line break to end a fence.
            code = "\n".join(complete) + "\n" if complete else ""
            self._code_open = False
            self._code_tail = ""
            return "", code, ""
        self._code_tail = lines[-1]
        if not complete:
            return "", "", ""
        return "", "\n".join(complete) + "\n", ""

    def full_html(self) -> str:
        """Render the whole source in one pass.

        Used once a stream finishes so transient splits (an unterminated
        formula that only became valid later, a reference link defined after
        its use) can never leave a stale fragment on screen.
        """

        return (
            _style_html(self._dark)
            + f'<div class="markdown-body">{render_body(self._source)}</div>'
        )
