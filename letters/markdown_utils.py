import markdown
import nh3

def render_markdown_safe(text: str) -> str:
    html = markdown.markdown(
        text or "",
        extensions=["extra", "sane_lists"],
        output_format="html5",
    )
    return nh3.clean(
        html,
        tags={"p", "em", "strong", "ul", "ol", "li", "blockquote", "a", "span", "h1", "h2", "h3", "code"},
        attributes={"a": {"href", "title"}, "span": {"style"}},
    )
