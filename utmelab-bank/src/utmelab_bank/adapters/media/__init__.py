"""Media adapters: a stateless GitLab store, plus local and in-memory ones."""

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
from .gitlab_store import GitLabMediaStore
from .ingest import (
    HttpMediaFetcher,
    MediaFetcher,
    MediaIngestor,
    MediaValidator,
    PillowMediaValidator,
    ingest_media_task,
)
from .local_store import LocalMediaStore
from .ocr_space import OcrSpaceClient, OcrSpaceError
from .paths import extension_for, is_blob_name, name_for, path_for, sha256_of
from .service import MediaService

__all__ = [
    "ConsensusPolicy",
    "DescribeImageConsensus",
    "Dissent",
    "GitLabMediaStore",
    "HttpMediaFetcher",
    "ImageDescriberService",
    "LocalMediaStore",
    "OcrSpaceClient",
    "OcrSpaceError",
    "MediaAuthError",
    "MediaError",
    "MediaFetcher",
    "MediaIngestor",
    "MediaPublishError",
    "MediaService",
    "MediaValidator",
    "MissingWitness",
    "PillowMediaValidator",
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
