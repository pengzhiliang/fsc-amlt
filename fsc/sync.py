"""
Sync service for keeping the local database up-to-date with AMLT.
Runs in the background and periodically fetches job status.
"""

import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Optional, List
import logging

from .models import (
    Experiment, Job, Project, SyncLog, 
    init_database, database
)
from .amlt_parser import (
    AmltParser, ExperimentInfo, ExperimentDetail,
    get_experiments, get_experiment_status
)

logger = logging.getLogger(__name__)


class SyncService:
    """
    Background service for syncing AMLT job status to local database.
    """
    
    def __init__(
        self,
        sync_interval: int = 60,  # seconds
        detail_sync_interval: int = 300,  # seconds for detailed status
        max_experiments: int = 100,
        on_update: Optional[Callable] = None,
    ):
        self.sync_interval = sync_interval
        self.detail_sync_interval = detail_sync_interval
        self.max_experiments = max_experiments
        self.on_update = on_update
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_sync = None
        self._last_detail_sync = None
        self._lock = threading.Lock()
    
    def start(self):
        """Start the background sync thread."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._sync_loop, daemon=True)
        self._thread.start()
        logger.info("Sync service started")
    
    def stop(self):
        """Stop the background sync thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Sync service stopped")
    
    def _sync_loop(self):
        """Main sync loop running in background thread."""
        while self._running:
            try:
                self.sync_list()
                
                # Check if we need to do detailed sync
                if (
                    self._last_detail_sync is None or
                    (datetime.now() - self._last_detail_sync).seconds >= self.detail_sync_interval
                ):
                    self.sync_active_experiments()
                    self._last_detail_sync = datetime.now()
                
                if self.on_update:
                    self.on_update()
                    
            except Exception as e:
                logger.error(f"Sync error: {e}")
            
            # Sleep in small increments to allow quick shutdown
            for _ in range(self.sync_interval):
                if not self._running:
                    break
                time.sleep(1)
    
    def sync_list(self, n_recent: int = None) -> bool:
        """
        Sync experiment list from `amlt list`.
        This is a fast operation that updates basic experiment info.
        """
        if n_recent is None:
            n_recent = self.max_experiments
        
        start_time = time.time()
        
        try:
            experiments = get_experiments(n_recent)
            
            with self._lock:
                with database.atomic():
                    for exp_info in experiments:
                        self._upsert_experiment(exp_info)
            
            duration = int(time.time() - start_time)
            SyncLog.create(
                sync_type="list",
                success=True,
                message=f"Synced {len(experiments)} experiments",
                duration_seconds=duration
            )
            
            self._last_sync = datetime.now()
            logger.debug(f"List sync completed: {len(experiments)} experiments")
            return True
            
        except Exception as e:
            SyncLog.create(
                sync_type="list",
                success=False,
                message=str(e)
            )
            logger.error(f"List sync failed: {e}")
            return False
    
    def sync_experiment_status(self, exp_name: str) -> bool:
        """
        Sync detailed status for a specific experiment.
        This fetches individual job status within the experiment.
        """
        start_time = time.time()
        
        try:
            detail = get_experiment_status(exp_name)
            if not detail:
                return False
            
            with self._lock:
                with database.atomic():
                    self._update_experiment_detail(exp_name, detail)
            
            duration = int(time.time() - start_time)
            SyncLog.create(
                sync_type="status",
                experiment_name=exp_name,
                success=True,
                message=f"Synced {len(detail.jobs)} jobs",
                duration_seconds=duration
            )
            
            logger.debug(f"Status sync completed for {exp_name}: {len(detail.jobs)} jobs")
            return True
            
        except Exception as e:
            SyncLog.create(
                sync_type="status",
                experiment_name=exp_name,
                success=False,
                message=str(e)
            )
            logger.error(f"Status sync failed for {exp_name}: {e}")
            return False
    
    def sync_active_experiments(self) -> int:
        """
        Sync detailed status for all active (non-terminal) experiments.
        Returns number of experiments synced.
        """
        count = 0
        
        # Get experiments that are not in terminal states
        active_statuses = ['running', 'prep', 'queued', 'unknown']
        
        try:
            experiments = Experiment.select().where(
                Experiment.status.in_(active_statuses) |
                (Experiment.detail_fetched == False)
            ).order_by(Experiment.updated_at.desc()).limit(20)
            
            for exp in experiments:
                if self.sync_experiment_status(exp.name):
                    count += 1
                time.sleep(0.5)  # Rate limiting
            
            return count
            
        except Exception as e:
            logger.error(f"Active sync failed: {e}")
            return count
    
    def force_sync_all(self) -> bool:
        """Force a full sync of all experiments."""
        success = self.sync_list()
        if success:
            # Sync details for recent experiments
            experiments = Experiment.select().order_by(
                Experiment.updated_at.desc()
            ).limit(30)
            
            for exp in experiments:
                self.sync_experiment_status(exp.name)
                time.sleep(0.3)
        
        return success
    
    def _upsert_experiment(self, exp_info: ExperimentInfo):
        """Insert or update an experiment from list info."""
        exp, created = Experiment.get_or_create(
            name=exp_info.name,
            defaults={
                'status': exp_info.status_type.lower(),
                'job_count': exp_info.status_count,
                'cluster': exp_info.cluster,
                'flags': exp_info.flags,
                'size': exp_info.size,
                'job_url': exp_info.job_url,
                'description': exp_info.description,
                'modified_at_str': exp_info.modified,
            }
        )
        
        if not created:
            # Update existing experiment
            exp.status = exp_info.status_type.lower()
            exp.job_count = exp_info.status_count
            exp.cluster = exp_info.cluster
            exp.flags = exp_info.flags
            exp.size = exp_info.size
            exp.job_url = exp_info.job_url
            exp.description = exp_info.description
            exp.modified_at_str = exp_info.modified
            exp.save()
    
    def _update_experiment_detail(self, exp_name: str, detail: ExperimentDetail):
        """Update experiment with detailed status info."""
        try:
            exp = Experiment.get(Experiment.name == exp_name)
        except Experiment.DoesNotExist:
            # Create new experiment
            exp = Experiment.create(
                name=exp_name,
                status='unknown',
            )
        
        # Update experiment info
        exp.service = detail.service
        exp.cluster = detail.cluster
        exp.workspace = detail.workspace
        exp.job_count = detail.n_jobs
        exp.description = detail.description
        exp.pass_count = detail.pass_count
        exp.fail_count = detail.fail_count
        exp.running_count = detail.running_count
        exp.queued_count = detail.queued_count
        exp.detail_fetched = True
        
        # Determine overall status from counts
        if detail.running_count > 0:
            exp.status = 'running'
        elif detail.queued_count > 0:
            exp.status = 'queued'
        elif detail.fail_count > 0:
            exp.status = 'fail'
        elif detail.pass_count > 0 and detail.pass_count == detail.n_jobs:
            exp.status = 'pass'
        
        exp.save()
        
        # Update jobs
        Job.delete().where(Job.experiment == exp).execute()
        
        for job_info in detail.jobs:
            Job.create(
                experiment=exp,
                job_index=job_info.index,
                job_name=job_info.name,
                status=job_info.status.lower(),
                duration=job_info.duration,
                size=job_info.size,
                flags=job_info.flags,
                portal_url=job_info.portal_url,
                submitted_at_str=job_info.submitted,
            )
    
    @property
    def last_sync_time(self) -> Optional[datetime]:
        """Get the last sync time."""
        return self._last_sync
    
    @property
    def is_running(self) -> bool:
        """Check if sync service is running."""
        return self._running


# Global sync service instance
_sync_service: Optional[SyncService] = None


def get_sync_service() -> SyncService:
    """Get or create the global sync service instance."""
    global _sync_service
    if _sync_service is None:
        _sync_service = SyncService()
    return _sync_service


def start_sync_service(**kwargs) -> SyncService:
    """Start the global sync service."""
    global _sync_service
    _sync_service = SyncService(**kwargs)
    _sync_service.start()
    return _sync_service


def stop_sync_service():
    """Stop the global sync service."""
    global _sync_service
    if _sync_service:
        _sync_service.stop()
        _sync_service = None
