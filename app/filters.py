from markupsafe import Markup
import markdown


def render_markdown(value):
    """Render trusted learning content from Markdown to HTML."""
    if not value:
        return ""

    html = markdown.markdown(
        str(value),
        extensions=["extra", "sane_lists", "nl2br"],
        output_format="html5",
    )
    return Markup(html)


def register_filters(app):
    app.jinja_env.filters["markdown"] = render_markdown
