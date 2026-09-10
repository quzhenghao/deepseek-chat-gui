from __future__ import annotations

import html
import re

from markdown_it import MarkdownIt


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

# These environments are commonly emitted by chat models without an additional
# \[...\] or $$...$$ wrapper. KaTeX treats them as display mathematics.
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

    # KaTeX already receives displayMode=True. Document-level environments are
    # converted to their embeddable equivalents while matrices/cases/aligned
    # inside the expression remain completely intact.
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

    # Labels have no useful meaning in a chat message and KaTeX intentionally
    # does not implement cross-document references.
    return re.sub(r"\\label\{[^{}]*\}", "", normalized)


def _extract_math(text: str) -> tuple[str, list[tuple[str, str, bool]]]:
    """Replace formulas outside Markdown code spans/fences with safe tokens."""

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


def to_html(text: str, dark: bool = False) -> str:
    """Render Markdown to a safe fragment containing KaTeX formula placeholders."""

    foreground = "#F2F2F2" if dark else "#171717"
    secondary = "#B7B7B7" if dark else "#5E5E5E"
    code_background = "#151515" if dark else "#F4F4F4"
    border = "#3A3A3A" if dark else "#E3E3E3"
    scroll_track = "#242424" if dark else "#EEEEEE"
    scroll_thumb = "#858585" if dark else "#8F8F8F"
    error = "#FF8A8A" if dark else "#B42318"

    source, formulas = _extract_math(text or "")
    rendered = _MARKDOWN.render(source) if source else ""
    rendered = _decorate_code_blocks(rendered)
    for token, expression, display in formulas:
        formula = _formula_html(expression, display)
        if display:
            rendered = rendered.replace(f"<p>{token}</p>", formula)
        rendered = rendered.replace(token, formula)

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
        font-family:Menlo, Monaco, Consolas, monospace; text-transform:none; }}
      .markdown-body .code-copy {{ flex:none; color:{secondary}; background:transparent;
        border:1px solid transparent; border-radius:6px; padding:3px 8px; font-size:11px;
        cursor:pointer; }}
      .markdown-body .code-copy:hover {{ color:{foreground}; background:{border}; }}
      .markdown-body .code-copy.is-copied {{ color:{foreground}; background:{border}; }}
      .markdown-body pre {{ margin:0; padding:12px 14px; background:{code_background};
        white-space:pre; overflow-x:auto; overflow-y:hidden; }}
      .markdown-body pre code {{ display:block; font-family:Menlo, Monaco, Consolas, monospace;
        color:{foreground}; background:transparent; line-height:1.55; font-size:13px; }}
      .markdown-body :not(pre) > code:not(.math-source) {{
        font-family:Menlo, Monaco, Consolas, monospace;
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
        font-family:Menlo, Monaco, Consolas, monospace; }}
    </style>
    <div class="markdown-body">{rendered or html.escape(text or '')}</div>
    """
