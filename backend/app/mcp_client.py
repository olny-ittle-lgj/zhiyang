from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from .config import settings


logger = logging.getLogger("zhiyan.fetch_mcp")


class FetchMcpError(RuntimeError):
    """Raised when the configured Fetch MCP cannot return page content."""


class FetchMcpNotConfigured(FetchMcpError):
    """Raised when URL extraction has not been configured yet."""


class _HtmlTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "template"}:
            self._ignored += 1
        elif tag in {"br", "p", "div", "article", "section", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "template"} and self._ignored:
            self._ignored -= 1
        elif tag in {"p", "div", "article", "section", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored:
            self.parts.append(data)


def normalize_page_content(content: str, max_chars: int | None = None) -> str:
    """Normalize MCP text/HTML output into readable, bounded material text."""
    value = content.replace("\x00", "").strip()
    if re.search(r"<\s*(html|body|article|main|section|p|h[1-6]|div)\b", value, re.IGNORECASE):
        parser = _HtmlTextParser()
        try:
            parser.feed(value)
            value = "".join(parser.parts)
        except Exception:
            logger.debug("MCP content was not valid HTML; preserving source text", exc_info=True)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value).strip()
    limit = max_chars or settings.fetch_mcp_max_chars
    return value[:limit].rstrip()


def _text_from_result(result: object) -> str:
    if getattr(result, "isError", False) or (isinstance(result, dict) and result.get("isError")):
        raise FetchMcpError("Fetch MCP 返回了工具错误")

    content = getattr(result, "content", None)
    if content is None and isinstance(result, dict):
        content = result.get("content")
    parts: list[str] = []
    for item in content or []:
        item_type = getattr(item, "type", None) or (item.get("type") if isinstance(item, dict) else None)
        if item_type == "text":
            text = getattr(item, "text", None) or (item.get("text") if isinstance(item, dict) else None)
            if text:
                parts.append(str(text))
        elif item_type == "resource":
            resource = getattr(item, "resource", None) or (item.get("resource") if isinstance(item, dict) else None)
            text = getattr(resource, "text", None) or (resource.get("text") if isinstance(resource, dict) else None)
            if text:
                parts.append(str(text))
    if not parts:
        raise FetchMcpError("Fetch MCP 未返回可读取的文本内容")
    return "\n\n".join(parts)


def _mcp_headers() -> dict[str, str] | None:
    return {"Authorization": f"Bearer {settings.fetch_mcp_token}"} if settings.fetch_mcp_token else None


def _transport_name() -> str:
    configured = settings.fetch_mcp_transport
    if configured in {"streamable_http", "streamable-http", "http"}:
        return "streamable_http"
    if configured == "sse":
        return "sse"
    return "streamable_http" if settings.fetch_mcp_url.rstrip("/").endswith("/mcp") else "sse"


async def _ensure_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise FetchMcpError("Only public HTTP(S) URLs can be collected")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise FetchMcpError("Local and private network URLs cannot be collected")

    try:
        addresses = [ipaddress.ip_address(hostname)]
    except ValueError:
        try:
            resolved = await asyncio.to_thread(
                socket.getaddrinfo,
                hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise FetchMcpError(f"Could not resolve the page host: {hostname}") from exc
        addresses = list({ipaddress.ip_address(item[4][0]) for item in resolved})

    if not addresses or any(not address.is_global for address in addresses):
        raise FetchMcpError("Local and private network URLs cannot be collected")


async def _fetch_direct(url: str) -> str:
    import httpx

    current_url = url
    max_bytes = min(max(settings.fetch_mcp_max_chars * 4, 256_000), 4_000_000)
    headers = {
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
        "User-Agent": "Mozilla/5.0 (compatible; ZhiyanCollector/1.0)",
    }
    timeout = httpx.Timeout(settings.fetch_direct_timeout)

    async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=False) as client:
        for _ in range(6):
            await _ensure_public_url(current_url)
            async with client.stream("GET", current_url) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise FetchMcpError("The page returned a redirect without a destination")
                    current_url = urljoin(str(response.url), location)
                    continue

                response.raise_for_status()
                content_type = response.headers.get("content-type", "").partition(";")[0].lower()
                if content_type and not (
                    content_type.startswith("text/")
                    or content_type in {"application/xhtml+xml", "application/xml", "application/json"}
                ):
                    raise FetchMcpError(f"Unsupported page content type: {content_type}")

                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    remaining = max_bytes - total
                    if remaining <= 0:
                        break
                    chunks.append(chunk[:remaining])
                    total += min(len(chunk), remaining)
                encoding = response.encoding or "utf-8"
                content = b"".join(chunks).decode(encoding, errors="replace")
                normalized = normalize_page_content(content)
                if not normalized:
                    raise FetchMcpError("The page did not return readable text")
                return normalized

    raise FetchMcpError("The page redirected too many times")


async def _call_streamable_http(arguments: dict[str, object]) -> object:
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with httpx.AsyncClient(headers=_mcp_headers(), timeout=settings.fetch_mcp_timeout) as http_client:
        async with streamable_http_client(settings.fetch_mcp_url, http_client=http_client) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                return await session.call_tool(settings.fetch_mcp_tool, arguments=arguments)


async def _call_sse(arguments: dict[str, object]) -> object:
    from mcp import ClientSession
    from mcp.client.sse import sse_client

    async with sse_client(
        settings.fetch_mcp_url,
        headers=_mcp_headers(),
        timeout=settings.fetch_mcp_timeout,
        sse_read_timeout=settings.fetch_mcp_timeout,
    ) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await session.call_tool(settings.fetch_mcp_tool, arguments=arguments)


async def fetch_url_content(url: str) -> str:
    """Call the configured Fetch MCP over Streamable HTTP or legacy SSE."""
    if not settings.fetch_mcp_url:
        raise FetchMcpNotConfigured("尚未配置 Fetch MCP 地址")

    await _ensure_public_url(url)
    direct_error: Exception | None = None
    try:
        return await _fetch_direct(url)
    except Exception as exc:
        direct_error = exc
        logger.info("Direct page fetch failed; falling back to Fetch MCP: %s", exc)

    try:
        arguments = {"url": url, "max_length": settings.fetch_mcp_max_chars}
        async with asyncio.timeout(settings.fetch_mcp_timeout):
            if _transport_name() == "streamable_http":
                result = await _call_streamable_http(arguments)
            else:
                result = await _call_sse(arguments)
            return normalize_page_content(_text_from_result(result))
    except FetchMcpError:
        raise
    except ImportError as exc:
        raise FetchMcpError("后端未安装 MCP Python SDK，请先安装 requirements.txt") from exc
    except Exception as exc:
        logger.warning("Fetch MCP request failed: %s", exc)
        direct_detail = str(direct_error).strip() if direct_error else "unknown error"
        mcp_detail = str(exc).strip() or exc.__class__.__name__
        raise FetchMcpError(
            f"Page collection failed (direct: {direct_detail[:100]}; MCP: {mcp_detail[:100]})"
        ) from exc
