# letters/templatetags/letter_markdown.py
from django import template
from letters.markdown_utils import render_markdown_safe

register = template.Library()

@register.filter(name="render_markdown")
def render_markdown(value):
    return render_markdown_safe(value or "")
