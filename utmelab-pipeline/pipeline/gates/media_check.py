"""Media URL reachability and validation."""

import httpx


async def check_media_reachability(url: str, timeout: float = 10.0) -> bool:
    """Checks whether a media URL exists, is reachable, and returns an image content-type."""
    if not url or not url.startswith(("http://", "https://")):
        return False

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.head(url)
            # Some servers reject HEAD requests; fallback to GET with byte range
            if resp.status_code in (405, 501):
                resp = await client.get(url, headers={"Range": "bytes=0-1024"})

            if resp.status_code not in (200, 206):
                return False

            content_type = resp.headers.get("content-type", "").lower()
            return content_type.startswith("image/") or "octet-stream" in content_type
    except Exception:
        return False
