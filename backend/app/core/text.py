import html
import re


def plain_text(rich: str | None) -> str | None:
    """Text of light HTML as card sources publish rules text (`<p>`, `<br>`, `<em>`)."""
    if not rich:
        return None
    text = re.sub(r"<br\s*/?>|</p>\s*<p>", "\n", rich)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return "\n".join(line.strip() for line in text.splitlines()).strip() or None
