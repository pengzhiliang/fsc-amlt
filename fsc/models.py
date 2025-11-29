"""
Database models for storing AMLT job information.
Uses SQLite with Peewee ORM for simplicity and portability.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from peewee import (
    BooleanField,
    CharField,
    DateTimeField,
    ForeignKeyField,
    IntegerField,
    Model,
    SqliteDatabase,
    TextField,
)

# Default database path
DEFAULT_DB_PATH = Path.home() / ".fsc" / "jobs.db"


def get_database(db_path: Optional[Path] = None) -> SqliteDatabase:
    """Get or create database connection."""
    if db_path is None:
        db_path = DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return SqliteDatabase(str(db_path), pragmas={
        'journal_mode': 'wal',
        'cache_size': -1024 * 64,  # 64MB cache
        'foreign_keys': 1,
        'synchronous': 0,
    })


# Database instance (will be initialized later)
database = SqliteDatabase(None)


class BaseModel(Model):
    """Base model with common fields."""
    created_at = DateTimeField(default=datetime.now)
    updated_at = DateTimeField(default=datetime.now)

    class Meta:
        database = database

    def save(self, *args, **kwargs):
        self.updated_at = datetime.now()
        return super().save(*args, **kwargs)


class Project(BaseModel):
    """AMLT Project information."""
    name = CharField(unique=True, index=True)
    path = CharField()  # Project root path
    is_active = BooleanField(default=False)

    class Meta:
        table_name = "projects"


class Experiment(BaseModel):
    """
    AMLT Experiment (corresponds to EXPERIMENT_NAME in amlt list).
    An experiment can contain one or more jobs (hyperdrive).
    """
    name = CharField(index=True)  # EXPERIMENT_NAME - unique identifier
    project = ForeignKeyField(Project, backref="experiments", null=True)
    
    # Status info (from amlt list)
    status = CharField(default="unknown")  # Running, Pass, Fail, Prep, etc.
    job_count = IntegerField(default=1)  # Number of jobs in this experiment
    
    # Cluster info
    cluster = CharField(null=True)
    workspace = CharField(null=True)
    service = CharField(null=True)  # sing, aml, etc.
    
    # Metadata
    description = CharField(null=True)
    flags = CharField(null=True)  # STD|HD, PRM|HD, etc.
    size = CharField(null=True)  # Result size
    job_url = CharField(null=True)  # Portal URL
    
    # Timing
    submitted_at = DateTimeField(null=True)
    modified_at_str = CharField(null=True)  # "1d ago", "2h ago", etc.
    
    # Detailed status counts (from amlt status)
    pass_count = IntegerField(default=0)
    fail_count = IntegerField(default=0)
    running_count = IntegerField(default=0)
    queued_count = IntegerField(default=0)
    
    # Whether detailed status has been fetched
    detail_fetched = BooleanField(default=False)
    
    class Meta:
        table_name = "experiments"
        indexes = (
            (("name", "project"), True),  # Unique constraint
        )


class Job(BaseModel):
    """
    Individual job within an experiment.
    For single-job experiments, there's one job.
    For hyperdrive experiments, there are multiple jobs.
    """
    experiment = ForeignKeyField(Experiment, backref="jobs", on_delete="CASCADE")
    
    # Job identification
    job_index = IntegerField()  # :0, :1, :2, etc.
    job_name = CharField(index=True)  # :n2-sft, :data_curation_264000, etc.
    
    # Status
    status = CharField(default="unknown")  # running, pass, fail, queued, etc.
    
    # Metadata
    duration = CharField(null=True)  # "17h", "4h", etc.
    size = CharField(null=True)
    flags = CharField(null=True)
    portal_url = CharField(null=True)
    
    # Timing
    submitted_at_str = CharField(null=True)  # "1d ago", etc.
    
    class Meta:
        table_name = "jobs"
        indexes = (
            (("experiment", "job_index"), True),  # Unique constraint
        )


class SyncLog(BaseModel):
    """Log of sync operations for debugging and tracking."""
    sync_type = CharField()  # "list", "status", "full"
    experiment_name = CharField(null=True)
    success = BooleanField(default=True)
    message = TextField(null=True)
    duration_seconds = IntegerField(null=True)

    class Meta:
        table_name = "sync_logs"


def init_database(db_path: Optional[Path] = None):
    """Initialize database connection and create tables."""
    global database
    if db_path is None:
        db_path = DEFAULT_DB_PATH
    
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    database.init(str(db_path), pragmas={
        'journal_mode': 'wal',
        'cache_size': -1024 * 64,
        'foreign_keys': 1,
        'synchronous': 0,
    })
    
    database.connect(reuse_if_open=True)
    database.create_tables([Project, Experiment, Job, SyncLog], safe=True)
    
    return database


def close_database():
    """Close database connection."""
    if not database.is_closed():
        database.close()
