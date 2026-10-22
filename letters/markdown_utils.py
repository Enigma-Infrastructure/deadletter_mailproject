import re

import markdown
import nh3

# Schemes that can execute code when used in an href (stored-XSS / code-injection vector).
_DANGEROUS_SCHEME = re.compile(
    r"^\s*(javascript|data|vbscript)",
    re.IGNORECASE,
)
_HREF_ATTR = re.compile(r'href=["\']([^"\']*)["\']')


def _strip_dangerous_href(match: re.Match) -> str:
    """Remove an href attribute whose value uses a dangerous scheme."""
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
        tags={"p", "em", "strong", "ul", "ol", "li", "blockquote", "a", "span", "h1", "h2", "h3", "code"},
        attributes={"a": {"href", "title"}, "span": {"style"}},
    )
    # Belt-and-suspenders: strip dangerous schemes from href even if the
    # sanitizer allows the attribute (e.g. `javascript:alert(1)`).
    html = _HREF_ATTR.sub(_strip_dangerous_href, html)
    return html
