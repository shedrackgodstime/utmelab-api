"""Media tasks: fetch, transform, upload, report, gc.

``media-discover`` (in ``task.gates``) records figure urls without fetching.
``media_fetch`` downloads the bytes into the media clone. The remaining steps
are specified later.
"""

from __future__ import annotations

from utmelab_bank.task.media.fetch import MediaFetch

__all__: list[str] = ["MediaFetch"]
