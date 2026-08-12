"""Safe source discovery, acquisition, and catalog dispatch boundaries."""

from .connectors import (
    Candidate,
    GitHubAdvisoryConnector,
    GitHubReleaseConnector,
    HTMLConnector,
    RSSConnector,
    SitemapConnector,
)
from .dispatcher import (
    DispatchReceipt,
    DispatchStatus,
    IngestionDispatcher,
    RuntimeDisposition,
    RuntimeOperation,
    UnsupportedSourceError,
    catalog_runtime_coverage,
    runtime_plan,
)
from .security import FetchPolicy, RawArtifact, SafeFetcher, UnsafeTargetError

__all__ = [
    "Candidate",
    "DispatchReceipt",
    "DispatchStatus",
    "FetchPolicy",
    "GitHubAdvisoryConnector",
    "GitHubReleaseConnector",
    "HTMLConnector",
    "IngestionDispatcher",
    "RSSConnector",
    "RawArtifact",
    "RuntimeDisposition",
    "RuntimeOperation",
    "SafeFetcher",
    "SitemapConnector",
    "UnsafeTargetError",
    "UnsupportedSourceError",
    "catalog_runtime_coverage",
    "runtime_plan",
]
