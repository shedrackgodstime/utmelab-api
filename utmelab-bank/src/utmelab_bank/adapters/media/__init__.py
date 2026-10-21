"""Media adapters. Git-backed storage with a GitLab remote."""

from .consensus import (
    ConsensusPolicy,
    DescribeImageConsensus,
    Dissent,
    MissingWitness,
    WitnessError,
)
from .describe import ImageDescriberService, create_describer
from .errors import MediaAuthError, MediaError, MediaPublishError
from .factory import create_media_store
from .git_store import BlobRef, GitMediaStore, PushReport
from .ingest import (
    HttpMediaFetcher,
    MediaFetcher,
    MediaIngestor,
    MediaValidator,
    PillowMediaValidator,
    ingest_media_task,
)
from .paths import extension_for, is_blob_name, name_for, path_for, sha256_of
from .service import MediaService

__all__ = [
    "BlobRef",
    "ConsensusPolicy",
    "DescribeImageConsensus",
    "Dissent",
    "GitMediaStore",
    "HttpMediaFetcher",
    "ImageDescriberService",
    "MediaAuthError",
    "MediaError",
    "MediaFetcher",
    "MediaIngestor",
    "MediaPublishError",
    "MediaService",
    "MediaValidator",
    "MissingWitness",
    "PillowMediaValidator",
    "PushReport",
    "WitnessError",
    "create_describer",
    "create_media_store",
    "extension_for",
    "ingest_media_task",
    "is_blob_name",
    "name_for",
    "path_for",
    "sha256_of",
]
