"""
Web fetch tool for TermPipe MCP Server.
Fetches the full content of a URL and returns it as clean text.
Supports pagination via offset + keep_reading for large pages.
"""

import re
import requests
from html.parser import HTMLParser


HARD_CAP_CHARS  = 10_000  # absolute ceiling per chunk — non-negotiable
DEFAULT_CHARS   =  5_000  # default chunk size if caller omits max_chars
STREAM_MAX      = 200_000 # max bytes to stream from server before stopping


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.chunks = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "head"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "head"):
            self._skip = False
        if tag in ("p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr"):
            self.chunks.append("\n")

    def handle_data(self, data):
        if not self._skip:
            stripped = data.strip()
            if stripped:
                self.chunks.append(stripped)


def _fetch_and_extract(url: str, raw: bool) -> str:
    """Fetch URL, stream up to STREAM_MAX bytes, return extracted text."""
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
    }

    response = requests.get(url, headers=headers, timeout=30, allow_redirects=True, stream=True)

    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}")

    content_type = response.headers.get("content-type", "")

    # Stream only up to STREAM_MAX — never pull a huge file into memory
    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=8192, decode_unicode=True):
        if chunk:
            chunks.append(chunk)
            total += len(chunk)
            if total >= STREAM_MAX:
                break
    raw_text = "".join(chunks)

    if raw or "text/plain" in content_type:
        return raw_text

    # Strip HTML
    extractor = _TextExtractor()
    extractor.feed(raw_text)
    text = " ".join(extractor.chunks)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text


def register_tools(mcp):
    """Register web fetch tools with the MCP server."""

    @mcp.tool()
    def web_fetch(
        url: str,
        max_chars: int = DEFAULT_CHARS,
        offset: int = 0,
        keep_reading: bool = False,
        raw: bool = False,
    ) -> str:
        """
        Fetch the content of a URL and return it as readable text.

        Supports pagination for large pages — the response footer always shows
        the next offset so you can continue reading without guessing.

        Args:
            url:          The URL to fetch.
            max_chars:    Characters to return this call (default: 5000, hard cap: 10000).
            offset:       Character offset to start from (default: 0 = beginning).
                          Copy the value from the previous response's "NEXT OFFSET" footer.
            keep_reading: Convenience alias — if True and offset is 0, has no effect.
                          Set offset to the previous response's next_offset value to continue.
            raw:          If True, return raw HTML instead of extracted text (default: False).
        """
        max_chars = min(max_chars, HARD_CAP_CHARS)

        try:
            full_text = _fetch_and_extract(url, raw)
        except RuntimeError as e:
            return f"[Error: {e} fetching {url}]"
        except requests.exceptions.Timeout:
            return f"[Error: Timeout fetching {url}]"
        except requests.exceptions.ConnectionError as e:
            return f"[Error: Connection error — {e}]"
        except Exception as e:
            return f"[Error: Unexpected error — {e}]"

        total_chars = len(full_text)

        # Slice the requested window
        chunk = full_text[offset : offset + max_chars]
        next_offset = offset + len(chunk)
        has_more = next_offset < total_chars

        header = f"🌐 Fetched: {url}\n{'=' * 60}\n"
        header += f"📄 Showing chars {offset}–{next_offset} of ~{total_chars} total\n\n"

        footer = ""
        if has_more:
            footer = (
                f"\n\n{'=' * 60}\n"
                f"⏩ MORE CONTENT AVAILABLE\n"
                f"   Call again with:  offset={next_offset}  (or keep_reading=True, offset={next_offset})\n"
                f"   Remaining: ~{total_chars - next_offset} chars"
            )
        else:
            footer = f"\n\n{'=' * 60}\n✅ END OF PAGE"

        return header + chunk + footer
