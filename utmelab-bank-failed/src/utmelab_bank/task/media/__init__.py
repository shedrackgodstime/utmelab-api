"""Media tasks: fetch, transform, upload, report, gc.

``media-discover`` (in ``task.gates``) records figure urls without fetching.
``media-fetch`` downloads the bytes into the media clone. ``media-upload``
publishes the clone and rewrites the owning question to our path. Transform,
report and gc are specified later.
"""

from __future__ import annotations

from utmelab_bank.task.media.fetch import MediaFetch
from utmelab_bank.task.media.upload import MediaUpload

__all__: list[str] = ["MediaFetch", "MediaUpload"]
