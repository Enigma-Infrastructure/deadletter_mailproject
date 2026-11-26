"""Safe Markdown rendering for Spacemarches archives, forums, and dossiers."""
import re

import markdown
import nh3

_DANGEROUS_SCHEME = re.compile(r"^\s*(javascript|data|vbscript)", re.IGNORECASE)
_HREF_ATTR = re.compile(r'href=["\']([^"\']*)["\']')


def _strip_dangerous_href(match: re.Match) -> str:
    value = match.group(1)
    if _DANGEROUS_SCHEME.match(value):
        return ""
    return match.group(0)


def render_markdown_safe(text: str) -> str:
    html = markdown.markdown(
        text or "",
        extensions=["extra", "sane_lists"],
        output_format="html5",
    )
    html = nh3.clean(
        html,
        tags={
            "p",
            "em",
            "strong",
            "ul",
            "ol",
            "li",
            "blockquote",
            "a",
            "span",
            "h1",
            "h2",
            "h3",
            "h4",
            "code",
            "pre",
            "hr",
        },
        attributes={"a": {"href", "title"}, "span": {"class"}},
    )
    return _HREF_ATTR.sub(_strip_dangerous_href, html)


def render_markdown_inline_safe(text: str) -> str:
    """Render sanitized Markdown for inline contexts (strips a single outer <p>...</p> wrapper)."""
    rendered = render_markdown_safe(text).strip()
    if rendered.startswith("<p>") and rendered.endswith("</p>") and rendered.count("<p>") == 1:
        return rendered[3:-4]
    return rendered
