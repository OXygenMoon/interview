from html import escape
from urllib.parse import urlsplit

from lxml import html as lxml_html
from markupsafe import Markup
import markdown


ALLOWED_MARKDOWN_TAGS = {
    'a', 'b', 'blockquote', 'br', 'code', 'del', 'em', 'h1', 'h2', 'h3',
    'h4', 'h5', 'h6', 'hr', 'i', 'img', 'li', 'ol', 'p', 'pre', 'strong',
    'table', 'tbody', 'td', 'th', 'thead', 'tr', 'ul',
}
ALLOWED_MARKDOWN_ATTRIBUTES = {
    'a': ['href', 'title'],
    'img': ['alt', 'height', 'src', 'title', 'width'],
    'td': ['colspan', 'rowspan'],
    'th': ['colspan', 'rowspan'],
}
DANGEROUS_HTML_TAGS = {
    'embed', 'iframe', 'math', 'noscript', 'object', 'script', 'style', 'svg',
    'template',
}
URI_ATTRIBUTES = {'href', 'src'}
ALLOWED_URI_SCHEMES = {'http', 'https', 'mailto'}


def _is_safe_uri(value):
    compact = ''.join(str(value).split()).lower()
    return not urlsplit(compact).scheme or urlsplit(compact).scheme in ALLOWED_URI_SCHEMES


def _sanitize_html(value):
    """Sanitize an HTML fragment using an explicit tag/attribute allowlist."""
    container = lxml_html.fragment_fromstring(value, create_parent='div')
    for element in list(container.iterdescendants()):
        if element.getparent() is None:
            continue
        if not isinstance(element.tag, str):
            element.drop_tree()
            continue

        tag = element.tag.lower()
        if tag in DANGEROUS_HTML_TAGS:
            element.drop_tree()
            continue
        if tag not in ALLOWED_MARKDOWN_TAGS:
            element.drop_tag()
            continue

        allowed_attributes = set(ALLOWED_MARKDOWN_ATTRIBUTES.get(tag, ()))
        for attribute, attribute_value in list(element.attrib.items()):
            normalized_attribute = attribute.lower()
            if normalized_attribute not in allowed_attributes:
                del element.attrib[attribute]
            elif (
                normalized_attribute in URI_ATTRIBUTES
                and not _is_safe_uri(attribute_value)
            ):
                del element.attrib[attribute]

    parts = [escape(container.text or '', quote=False)]
    parts.extend(
        lxml_html.tostring(child, encoding='unicode', method='html')
        for child in container
    )
    return ''.join(parts)


def render_markdown(value):
    """Render learning content and remove executable or unsafe HTML."""
    if not value:
        return ""

    html = markdown.markdown(
        str(value),
        extensions=["extra", "sane_lists", "nl2br"],
        output_format="html5",
    )
    sanitized = _sanitize_html(html)
    return Markup(sanitized)


def register_filters(app):
    app.jinja_env.filters["markdown"] = render_markdown
