"""
Cache manager for terminated experiments and config.
Stores experiments with terminal states (pass, fail, killed) locally
to avoid unnecessary API calls.
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Set, Any
from dataclasses import dataclass, asdict, field

# Terminal states that won't change
TERMINAL_STATES = {'pass', 'fail', 'failed', 'killed', 'cancelled'}

# Cache file paths
CACHE_DIR = Path.home() / ".fsc"
CACHE_FILE = CACHE_DIR / "experiment_cache.json"
CONFIG_CACHE_FILE = CACHE_DIR / "config_cache.json"
DETAIL_CACHE_FILE = CACHE_DIR / "detail_cache.json"


@dataclass
class CachedExperiment:
    """Cached experiment data."""
    name: str
    status: str
    status_str: str
    job_count: int
    cluster: str
    flags: str
    modified: str
    job_url: str
    running_count: int = 0
    queued_count: int = 0
    pass_count: int = 0
    fail_count: int = 0
    killed_count: int = 0
    cached_at: str = ""
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'CachedExperiment':
        return cls(**data)


@dataclass
class CachedJob:
    """Cached job data."""
    index: int
    name: str
    status: str
    duration: str = ""
    size: str = ""
    submitted: str = ""
    flags: str = ""
    portal_url: str = ""
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'CachedJob':
        return cls(**data)


@dataclass
class CachedExperimentDetail:
    """Cached experiment detail with jobs."""
    name: str
    cluster: str
    n_jobs: int
    pass_count: int = 0
    fail_count: int = 0
    running_count: int = 0
    queued_count: int = 0
    killed_count: int = 0
    jobs: List[CachedJob] = field(default_factory=list)
    cached_at: str = ""
    
    def to_dict(self) -> dict:
        d = asdict(self)
        d['jobs'] = [j.to_dict() if isinstance(j, CachedJob) else j for j in self.jobs]
        return d
    
    @classmethod
    def from_dict(cls, data: dict) -> 'CachedExperimentDetail':
        jobs = [CachedJob.from_dict(j) if isinstance(j, dict) else j for j in data.get('jobs', [])]
        data = dict(data)
        data['jobs'] = jobs
        return cls(**data)


class ExperimentCache:
    """
    Cache manager for terminated experiments.
    
    Experiments in terminal states (pass, fail, killed) are cached locally
    and won't be fetched again from the API.
    """
    
    def __init__(self, cache_file: Optional[Path] = None):
        self.cache_file = cache_file or CACHE_FILE
        self._cache: Dict[str, CachedExperiment] = {}
        self._load()
    
    def _load(self):
        """Load cache from disk."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    data = json.load(f)
                    self._cache = {
                        name: CachedExperiment.from_dict(exp_data)
                        for name, exp_data in data.items()
                    }
            except (json.JSONDecodeError, KeyError, TypeError):
                self._cache = {}
    
    def _save(self):
        """Save cache to disk."""
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, 'w') as f:
            json.dump(
                {name: exp.to_dict() for name, exp in self._cache.items()},
                f,
                indent=2
            )
    
    def is_terminal(self, status: str) -> bool:
        """Check if a status is terminal (won't change)."""
        return status.lower() in TERMINAL_STATES
    
    def get(self, name: str) -> Optional[CachedExperiment]:
        """Get a cached experiment by name."""
        return self._cache.get(name)
    
    def get_all(self) -> List[CachedExperiment]:
        """Get all cached experiments."""
        return list(self._cache.values())
    
    def get_by_status(self, status: str) -> List[CachedExperiment]:
        """Get cached experiments by status."""
        return [exp for exp in self._cache.values() if exp.status == status]
    
    def add(self, exp_data: dict):
        """
        Add an experiment to cache if it's in a terminal state.
        exp_data should have: name, status, and other ExpData fields.
        """
        status = exp_data.get('status', '').lower()
        if not self.is_terminal(status):
            return
        
        name = exp_data.get('name')
        if not name:
            return
        
        # Create cached experiment
        cached = CachedExperiment(
            name=name,
            status=status,
            status_str=exp_data.get('status_str', ''),
            job_count=exp_data.get('job_count', 1),
            cluster=exp_data.get('cluster', ''),
            flags=exp_data.get('flags', ''),
            modified=exp_data.get('modified', ''),
            job_url=exp_data.get('job_url', ''),
            running_count=exp_data.get('running_count', 0),
            queued_count=exp_data.get('queued_count', 0),
            pass_count=exp_data.get('pass_count', 0),
            fail_count=exp_data.get('fail_count', 0),
            killed_count=exp_data.get('killed_count', 0),
            cached_at=datetime.now().isoformat(),
        )
        
        self._cache[name] = cached
        self._save()
    
    def add_from_exp_data(self, exp):
        """Add from ExpData object."""
        self.add({
            'name': exp.name,
            'status': exp.status,
            'status_str': exp.status_str,
            'job_count': exp.job_count,
            'cluster': exp.cluster,
            'flags': exp.flags,
            'modified': exp.modified,
            'job_url': exp.job_url,
            'running_count': exp.running_count,
            'queued_count': exp.queued_count,
            'pass_count': exp.pass_count,
            'fail_count': exp.fail_count,
            'killed_count': exp.killed_count,
        })
    
    def update_status(self, name: str, status: str, pass_count: int = 0, fail_count: int = 0, 
                     killed_count: int = 0, running_count: int = 0, queued_count: int = 0):
        """Update an experiment's status in cache (used when detail view reveals true status)."""
        if name not in self._cache:
            return
        
        cached = self._cache[name]
        cached.status = status
        cached.pass_count = pass_count
        cached.fail_count = fail_count
        cached.killed_count = killed_count
        cached.running_count = running_count
        cached.queued_count = queued_count
        cached.cached_at = datetime.now().isoformat()
        self._save()
    
    def force_add(self, name: str, status: str, cluster: str = '', job_count: int = 1,
                  pass_count: int = 0, fail_count: int = 0, killed_count: int = 0):
        """Force add an experiment to cache regardless of current cache status."""
        if status not in TERMINAL_STATES:
            return
        
        cached = CachedExperiment(
            name=name,
            status=status,
            status_str=f"{status.capitalize()} ({job_count})",
            job_count=job_count,
            cluster=cluster,
            flags='',
            modified='',
            job_url='',
            running_count=0,
            queued_count=0,
            pass_count=pass_count,
            fail_count=fail_count,
            killed_count=killed_count,
            cached_at=datetime.now().isoformat(),
        )
        
        self._cache[name] = cached
        self._save()
    
    def remove(self, name: str):
        """Remove an experiment from cache."""
        if name in self._cache:
            del self._cache[name]
            self._save()
    
    def get_cached_names(self) -> Set[str]:
        """Get names of all cached experiments."""
        return set(self._cache.keys())
    
    def clear(self):
        """Clear all cached data."""
        self._cache = {}
        if self.cache_file.exists():
            self.cache_file.unlink()
    
    def stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        stats = {'total': len(self._cache)}
        for status in TERMINAL_STATES:
            stats[status] = len([e for e in self._cache.values() if e.status == status])
        return stats


# Global cache instance
_cache: Optional[ExperimentCache] = None


def get_cache() -> ExperimentCache:
    """Get the global cache instance."""
    global _cache
    if _cache is None:
        _cache = ExperimentCache()
    return _cache


class ConfigCache:
    """Cache for AMLT config values like output_dir."""
    
    def __init__(self):
        self.cache_file = CONFIG_CACHE_FILE
        self._config: Dict[str, str] = {}
        self._load()
    
    def _load(self):
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    self._config = json.load(f)
            except:
                self._config = {}
    
    def _save(self):
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, 'w') as f:
            json.dump(self._config, f, indent=2)
    
    def get(self, key: str) -> Optional[str]:
        return self._config.get(key)
    
    def set(self, key: str, value: str):
        self._config[key] = value
        self._save()
    
    def get_output_dir(self) -> str:
        """Get AMLT output directory, fetching from amlt project if not cached."""
        cached = self.get('output_dir')
        if cached:
            return cached
        
        # Fetch from amlt project
        try:
            result = subprocess.run(['amlt', 'project'], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'DEFAULT_OUTPUT_DIR' in line:
                        parts = line.split()
                        if len(parts) >= 2:
                            output_dir = parts[-1]
                            self.set('output_dir', output_dir)
                            return output_dir
        except:
            pass
        
        # Fallback
        import os
        return os.path.expanduser("~/amlt")


class DetailCache:
    """Cache for terminal experiment details (jobs list)."""
    
    def __init__(self):
        self.cache_file = DETAIL_CACHE_FILE
        self._cache: Dict[str, CachedExperimentDetail] = {}
        self._load()
    
    def _load(self):
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    data = json.load(f)
                    self._cache = {
                        name: CachedExperimentDetail.from_dict(detail)
                        for name, detail in data.items()
                    }
            except:
                self._cache = {}
    
    def _save(self):
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, 'w') as f:
            json.dump(
                {name: detail.to_dict() for name, detail in self._cache.items()},
                f,
                indent=2
            )
    
    def get(self, name: str) -> Optional[CachedExperimentDetail]:
        return self._cache.get(name)
    
    def add(self, name: str, detail: 'Any', jobs: List['Any']):
        """Add experiment detail to cache. Only caches terminal experiments.
        
        For multi-job experiments, use job :0's status to determine if terminal.
        """
        if not jobs:
            return
        
        # For multi-job experiments, check job :0's status
        # Job :0 is the "parent" job that represents the overall experiment status
        job0 = next((j for j in jobs if j.index == 0), None)
        
        if job0:
            job0_status = job0.status.lower().split()[0] if job0.status else ''
            # Only cache if job :0 is in terminal state
            if job0_status not in ('pass', 'fail', 'failed', 'killed'):
                return
        else:
            # Fallback: check if any running/queued jobs
            running = sum(1 for j in jobs if j.status.lower().split()[0] == 'running')
            queued = sum(1 for j in jobs if j.status.lower().split()[0] in ('queued', 'prep'))
            if running > 0 or queued > 0:
                return
        
        cached_jobs = [
            CachedJob(
                index=j.index,
                name=j.name,
                status=j.status.split()[0] if j.status else '',  # Get first word
                duration=j.duration,
                size=j.size,
                submitted=j.submitted,
                flags=j.flags,
                portal_url=j.portal_url,
            )
            for j in jobs
        ]
        
        pass_count = sum(1 for j in jobs if j.status.lower().split()[0] == 'pass')
        fail_count = sum(1 for j in jobs if j.status.lower().split()[0] in ('fail', 'failed'))
        killed_count = sum(1 for j in jobs if j.status.lower().split()[0] == 'killed')
        
        cached_detail = CachedExperimentDetail(
            name=name,
            cluster=detail.cluster if hasattr(detail, 'cluster') else '',
            n_jobs=len(jobs),
            pass_count=pass_count,
            fail_count=fail_count,
            running_count=0,
            queued_count=0,
            killed_count=killed_count,
            jobs=cached_jobs,
            cached_at=datetime.now().isoformat(),
        )
        
        self._cache[name] = cached_detail
        self._save()
    
    def has(self, name: str) -> bool:
        return name in self._cache
    
    def remove(self, name: str):
        """Remove an experiment from cache."""
        if name in self._cache:
            del self._cache[name]
            self._save()
    
    def clear(self):
        self._cache = {}
        if self.cache_file.exists():
            self.cache_file.unlink()


# Global instances
_config_cache: Optional[ConfigCache] = None
_detail_cache: Optional[DetailCache] = None


def get_config_cache() -> ConfigCache:
    global _config_cache
    if _config_cache is None:
        _config_cache = ConfigCache()
    return _config_cache


def get_detail_cache() -> DetailCache:
    global _detail_cache
    if _detail_cache is None:
        _detail_cache = DetailCache()
    return _detail_cache
