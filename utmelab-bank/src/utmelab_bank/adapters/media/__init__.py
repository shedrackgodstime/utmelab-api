"""Media adapters. Git-backed storage with GitLab remote."""

from .consensus import (
    ConsensusPolicy,
    DescribeImageConsensus,
    Dissent,
    MissingWitness,
    WitnessError,
)
from .describe import ImageDescriberService, create_describer
from .git_store import GitMediaStore
from .ingest import (
    HttpMediaFetcher,
    MediaFetcher,
    MediaIngestor,
    MediaValidator,
    PillowMediaValidator,
    ingest_media_task,
)
from .service import MediaService

__all__ = [
    "ConsensusPolicy",
    "DescribeImageConsensus",
    "Dissent",
    "GitMediaStore",
    "HttpMediaFetcher",
    "ImageDescriberService",
    "MediaFetcher",
    "MediaIngestor",
    "MediaService",
    "MediaValidator",
    "MissingWitness",
    "PillowMediaValidator",
    "WitnessError",
    "create_describer",
    "ingest_media_task",
]
