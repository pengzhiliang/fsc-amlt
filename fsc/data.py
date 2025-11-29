"""
Data classes for FSC TUI application.
These are simple data containers, not database models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .cache import TERMINAL_STATES
from .utils import parse_compound_status, get_primary_status


@dataclass
class ExpData:
    """Simple experiment data container (not a DB model)."""
    name: str
    status: str  # Primary status
    status_str: str  # Original status string like "Running (12), Queued (2)"
    job_count: int
    cluster: str
    flags: str
    modified: str
    job_url: str
    
    # Parsed counts from compound status
    running_count: int = 0
    queued_count: int = 0
    pass_count: int = 0
    fail_count: int = 0
    killed_count: int = 0
    
    # Whether this came from cache
    from_cache: bool = False
    
    @classmethod
    def from_info(cls, info) -> 'ExpData':
        """Create from ExperimentInfo."""
        status_counts = parse_compound_status(info.status)
        primary_status = get_primary_status(info.status)
        
        # Calculate total job count
        total_jobs = sum(status_counts.values()) if status_counts else info.status_count
        
        return cls(
            name=info.name,
            status=primary_status,
            status_str=info.status,
            job_count=total_jobs,
            cluster=info.cluster or '',
            flags=info.flags or '',
            modified=info.modified or '',
            job_url=info.job_url or '',
            running_count=status_counts.get('running', 0),
            queued_count=status_counts.get('queued', 0) + status_counts.get('prep', 0),
            pass_count=status_counts.get('pass', 0),
            fail_count=status_counts.get('fail', 0) + status_counts.get('failed', 0),
            killed_count=status_counts.get('killed', 0),
        )
    
    @classmethod
    def from_cached(cls, cached) -> 'ExpData':
        """Create from CachedExperiment."""
        return cls(
            name=cached.name,
            status=cached.status,
            status_str=cached.status_str,
            job_count=cached.job_count,
            cluster=cached.cluster,
            flags=cached.flags,
            modified=cached.modified,
            job_url=cached.job_url,
            running_count=cached.running_count,
            queued_count=cached.queued_count,
            pass_count=cached.pass_count,
            fail_count=cached.fail_count,
            killed_count=cached.killed_count,
            from_cache=True,
        )
    
    def is_terminal(self) -> bool:
        """Check if this experiment is in a terminal state."""
        return self.status in TERMINAL_STATES


@dataclass
class JobData:
    """Simple job data container."""
    index: int
    name: str
    status: str
    duration: str
    size: str
    submitted: str
    flags: str
    portal_url: str


@dataclass
class StatusChange:
    """Represents a status change notification."""
    exp_name: str
    old_status: str
    new_status: str
    timestamp: datetime = field(default_factory=datetime.now)
