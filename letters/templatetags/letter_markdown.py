# letters/templatetags/letter_markdown.py
import markdown
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def render_markdown(value):
    if not value:
        return ""
    return mark_safe(
        markdown.markdown(
            value,
            extensions=["nl2br", "fenced_code"],
        )
    )


@register.filter
def first_line(value):
    """Return the first non-empty line of a string, stripped of Markdown syntax."""
    if not value:
        return ""
    for line in value.splitlines():
        clean = line.strip().lstrip("#").strip()
        if clean:
            return clean
    return ""
