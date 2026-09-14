import re

import bleach

try:
    from bleach.css_sanitizer import CSSSanitizer

    _CSS = CSSSanitizer(allowed_css_properties=[
        'color', 'background-color', 'background', 'text-align',
        'font-weight', 'font-style', 'text-decoration',
    ])
except ImportError:
    _CSS = None

MAX_LESSON_HTML_BYTES = 512 * 1024

ALLOWED_TAGS = [
    'p', 'h1', 'h2', 'h3', 'strong', 'em', 'u', 's', 'span', 'mark',
    'ul', 'ol', 'li', 'br', 'blockquote', 'img', 'a', 'div',
]

ALLOWED_ATTRIBUTES = {
    '*': ['style', 'class'],
    'img': ['src', 'alt', 'title', 'width', 'height'],
    'a': ['href', 'title', 'target', 'rel'],
    'span': ['style'],
    'mark': ['style'],
}

ALLOWED_PROTOCOLS = ['http', 'https', 'mailto']


def sanitize_lesson_html(html):
    """Sanitize lesson HTML content. Returns cleaned HTML or raises ValueError."""
    if html is None:
        return ''
    text = str(html)
    if not text.strip():
        return ''
    if len(text.encode('utf-8')) > MAX_LESSON_HTML_BYTES:
        raise ValueError('Content exceeds maximum size')

    cleaned = bleach.clean(
        text,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
        css_sanitizer=_CSS,
    )
    cleaned = re.sub(r'on\w+\s*=\s*["\'][^"\']*["\']', '', cleaned, flags=re.I)
    return cleaned.strip()
