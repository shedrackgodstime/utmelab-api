"""Media adapters. Git-backed storage with GitLab remote."""

from .consensus import ConsensusPolicy, DescribeImageConsensus
from .describe import ImageDescriberService, create_describer
from .git_store import GitMediaStore
from .ingest import MediaFetcher, MediaIngestor, MediaValidator, ingest_media_task

__all__ = [
    "ConsensusPolicy",
    "DescribeImageConsensus",
    "GitMediaStore",
    "ImageDescriberService",
    "MediaFetcher",
    "MediaIngestor",
    "MediaValidator",
    "create_describer",
    "ingest_media_task",
]
