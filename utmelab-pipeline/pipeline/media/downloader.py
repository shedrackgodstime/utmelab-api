"""Media downloader with content-hash caching."""

import hashlib
from pathlib import Path
from typing import Optional
import httpx
from pipeline.config import config


class MediaDownloader:
    """Downloads diagrams and images, caching them locally by SHA-256 hash."""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or config.media_cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def get_or_download(self, url: str, timeout: float = 20.0) -> Optional[Path]:
        """Downloads an image from a URL or returns its cached path if already downloaded."""
        if not url or not url.startswith(("http://", "https://")):
            return None

        # Pre-compute URL hash to check for existing file
        url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
        matches = list(self.cache_dir.glob(f"{url_hash}.*"))
        if matches and matches[0].exists() and matches[0].stat().st_size > 0:
            return matches[0]

        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return None

                content_type = resp.headers.get("content-type", "").lower()
                ext = ".png"
                if "jpeg" in content_type or "jpg" in content_type:
                    ext = ".jpg"
                elif "gif" in content_type:
                    ext = ".gif"
                elif "webp" in content_type:
                    ext = ".webp"
                else:
                    # Determine by url suffix if available
                    path_ext = Path(url.split("?")[0]).suffix.lower()
                    if path_ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                        ext = path_ext

                file_path = self.cache_dir / f"{url_hash}{ext}"
                file_path.write_bytes(resp.content)
                return file_path
        except Exception:
            return None
