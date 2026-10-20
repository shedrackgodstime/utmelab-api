"""Media adapters. Git-backed storage with GitLab remote."""

from .git_store import GitMediaStore
from .ingest import MediaFetcher, MediaValidator, MediaIngestor, ingest_media_task
from .describe import ImageDescriberService, create_describer
from .consensus import ConsensusPolicy, DescribeImageConsensus

__all__ = [
    "GitMediaStore",
    "MediaFetcher",
    "MediaValidator",
    "MediaIngestor",
    "ingest_media_task",
    "ImageDescriberService",
    "create_describer",
    "ConsensusPolicy",
    "DescribeImageConsensus",
]