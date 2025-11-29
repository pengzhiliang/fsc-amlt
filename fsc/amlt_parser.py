"""
Parser for AMLT command output.
Parses the output of `amlt list` and `amlt status` commands.
"""

import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
import shlex


@dataclass
class ExperimentInfo:
    """Parsed experiment information from `amlt list`."""
    name: str
    modified: str  # "1d ago", "2h ago", etc.
    status: str  # "Running (1)", "Pass (33)", etc.
    cluster: str
    flags: str
    size: str
    job_url: str
    description: str
    
    # Parsed from status string
    status_type: str = ""  # Running, Pass, Fail, Prep, etc.
    status_count: int = 0  # Number in parentheses
    
    def __post_init__(self):
        # Parse status like "Running (1)" or "Pass (33)"
        match = re.match(r"(\w+)\s*\((\d+)\)", self.status)
        if match:
            self.status_type = match.group(1)
            self.status_count = int(match.group(2))
        else:
            self.status_type = self.status
            self.status_count = 1


@dataclass
class JobInfo:
    """Parsed job information from `amlt status`."""
    index: int  # :0, :1, etc.
    name: str  # :n2-sft, :data_curation_264000, etc.
    status: str  # running, pass, fail, queued, etc.
    duration: str = ""
    size: str = ""
    submitted: str = ""
    flags: str = ""
    portal_url: str = ""


@dataclass
class ExperimentDetail:
    """Detailed experiment information from `amlt status`."""
    name: str
    service: str
    cluster: str
    workspace: str
    n_jobs: int
    description: str
    
    # Status counts
    pass_count: int = 0
    fail_count: int = 0
    running_count: int = 0
    queued_count: int = 0
    
    # Individual jobs
    jobs: List[JobInfo] = field(default_factory=list)


def safe_int(value: str, default: int = 0) -> int:
    """Safely parse an integer, handling spaces and non-numeric values."""
    if not value:
        return default
    # Take only the first number if there are spaces
    try:
        return int(value.split()[0])
    except (ValueError, IndexError):
        return default


class AmltParser:
    """Parser for AMLT command outputs."""
    
    @staticmethod
    def run_amlt_command(cmd: List[str], timeout: int = 60) -> Tuple[bool, str, str]:
        """
        Run an amlt command and return (success, stdout, stderr).
        """
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=None,  # Use current environment
            )
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, "", f"Command timed out after {timeout}s"
        except Exception as e:
            return False, "", str(e)

    @staticmethod
    def parse_list_output(output: str) -> List[ExperimentInfo]:
        """
        Parse the output of `amlt list --most-recent N`.
        
        Example output:
        EXPERIMENT_NAME    MODIFIED    JOB_STATUS    CLUSTER    FLAGS    SIZE      JOB_URL    DESCRIPTION
        -----------------  ----------  ------------  ---------  -------  --------  ---------  -----------
        winning-joey       1d ago      Running (1)   cluster    STD|HD   0 Bytes   https://   Data Curation
        """
        experiments = []
        lines = output.strip().split('\n')
        
        # Find the header line and data lines
        header_idx = -1
        for i, line in enumerate(lines):
            if 'EXPERIMENT_NAME' in line and 'JOB_STATUS' in line:
                header_idx = i
                break
        
        if header_idx == -1:
            return experiments
        
        # Skip header and separator lines
        data_start = header_idx + 2
        if data_start >= len(lines):
            return experiments
        
        # Parse column positions from header
        header_line = lines[header_idx]
        columns = ['EXPERIMENT_NAME', 'MODIFIED', 'JOB_STATUS', 'CLUSTER', 'FLAGS', 'SIZE', 'JOB_URL', 'DESCRIPTION']
        col_positions = []
        
        for col in columns:
            pos = header_line.find(col)
            if pos >= 0:
                col_positions.append((col, pos))
        
        col_positions.sort(key=lambda x: x[1])
        
        # Parse each data line
        for line in lines[data_start:]:
            if not line.strip() or line.startswith('II ') or line.startswith('──'):
                continue
            
            # Skip empty lines between tables
            if all(c in ' -─│' for c in line):
                break
                
            # Extract values based on column positions
            values = {}
            for i, (col_name, start_pos) in enumerate(col_positions):
                if i + 1 < len(col_positions):
                    end_pos = col_positions[i + 1][1]
                    values[col_name] = line[start_pos:end_pos].strip()
                else:
                    values[col_name] = line[start_pos:].strip()
            
            if values.get('EXPERIMENT_NAME'):
                try:
                    exp = ExperimentInfo(
                        name=values.get('EXPERIMENT_NAME', ''),
                        modified=values.get('MODIFIED', ''),
                        status=values.get('JOB_STATUS', ''),
                        cluster=values.get('CLUSTER', ''),
                        flags=values.get('FLAGS', ''),
                        size=values.get('SIZE', ''),
                        job_url=values.get('JOB_URL', ''),
                        description=values.get('DESCRIPTION', ''),
                    )
                    experiments.append(exp)
                except Exception:
                    continue
        
        return experiments

    @staticmethod
    def parse_status_output(output: str) -> Optional[ExperimentDetail]:
        """
        Parse the output of `amlt status <experiment_name>`.
        
        The output contains two tables:
        1. Job list with columns: #, JOB_NAME, DURATION, STATUS, SIZE, SUBMITTED, FLAGS, PORTAL URL
        2. Summary with columns: EXPERIMENT_NAME, SERVICE, CLUSTER, WORKSPACE, N_JOBS, <STATUS_COUNTS>, DESCRIPTION
        """
        lines = output.strip().split('\n')
        
        jobs = []
        experiment_info = {}
        
        # Find job table
        job_header_idx = -1
        for i, line in enumerate(lines):
            if '#' in line and 'JOB_NAME' in line and 'STATUS' in line:
                job_header_idx = i
                break
        
        if job_header_idx >= 0:
            # Parse job table header to get column positions
            header_line = lines[job_header_idx]
            
            # Find column positions
            job_columns = ['#', 'JOB_NAME', 'DURATION', 'STATUS', 'SIZE', 'SUBMITTED', 'FLAGS', 'PORTAL URL']
            # Some tables don't have DURATION column
            if 'DURATION' not in header_line:
                job_columns = ['#', 'JOB_NAME', 'STATUS', 'SIZE', 'SUBMITTED', 'FLAGS', 'PORTAL URL']
            
            col_positions = []
            for col in job_columns:
                pos = header_line.find(col)
                if pos >= 0:
                    col_positions.append((col, pos))
            col_positions.sort(key=lambda x: x[1])
            
            # Parse job rows
            data_start = job_header_idx + 2  # Skip header and separator
            for line in lines[data_start:]:
                if not line.strip():
                    break
                if line.startswith('─') or line.startswith('-'):
                    continue
                if 'EXPERIMENT_NAME' in line:
                    break
                
                # Extract values
                values = {}
                for i, (col_name, start_pos) in enumerate(col_positions):
                    if i + 1 < len(col_positions):
                        end_pos = col_positions[i + 1][1]
                        values[col_name] = line[start_pos:end_pos].strip()
                    else:
                        values[col_name] = line[start_pos:].strip()
                
                if values.get('#', '').replace(':', '').isdigit():
                    try:
                        job = JobInfo(
                            index=int(values.get('#', ':0').replace(':', '')),
                            name=values.get('JOB_NAME', ''),
                            status=values.get('STATUS', ''),
                            duration=values.get('DURATION', ''),
                            size=values.get('SIZE', ''),
                            submitted=values.get('SUBMITTED', ''),
                            flags=values.get('FLAGS', ''),
                            portal_url=values.get('PORTAL URL', ''),
                        )
                        jobs.append(job)
                    except (ValueError, KeyError):
                        continue
        
        # Find experiment summary table
        summary_header_idx = -1
        for i, line in enumerate(lines):
            if 'EXPERIMENT_NAME' in line and 'SERVICE' in line and 'CLUSTER' in line:
                summary_header_idx = i
                break
        
        if summary_header_idx >= 0:
            header_line = lines[summary_header_idx]
            
            # Dynamic column detection - some experiments have different status columns
            base_columns = ['EXPERIMENT_NAME', 'SERVICE', 'CLUSTER', 'WORKSPACE', 'N_JOBS']
            status_columns = []
            
            # Check for different status columns (including KILLED)
            for status_col in ['PASS', 'FAIL', 'RUNNING', 'QUEUED', 'PREP', 'KILLED']:
                if status_col in header_line:
                    status_columns.append(status_col)
            
            all_columns = base_columns + status_columns + ['DESCRIPTION']
            
            col_positions = []
            for col in all_columns:
                pos = header_line.find(col)
                if pos >= 0:
                    col_positions.append((col, pos))
            col_positions.sort(key=lambda x: x[1])
            
            # Parse summary row
            data_start = summary_header_idx + 2
            if data_start < len(lines):
                line = lines[data_start]
                values = {}
                for i, (col_name, start_pos) in enumerate(col_positions):
                    if i + 1 < len(col_positions):
                        end_pos = col_positions[i + 1][1]
                        values[col_name] = line[start_pos:end_pos].strip()
                    else:
                        values[col_name] = line[start_pos:].strip()
                
                experiment_info = values
        
        if not experiment_info.get('EXPERIMENT_NAME'):
            return None
        
        # Count job statuses using safe_int
        pass_count = safe_int(experiment_info.get('PASS', ''), 0)
        fail_count = safe_int(experiment_info.get('FAIL', ''), 0)
        running_count = safe_int(experiment_info.get('RUNNING', ''), 0)
        queued_count = safe_int(experiment_info.get('QUEUED', ''), 0)
        killed_count = safe_int(experiment_info.get('KILLED', ''), 0)
        
        # If no status columns, count from jobs
        if not any([pass_count, fail_count, running_count, queued_count, killed_count]):
            for job in jobs:
                status_lower = job.status.lower().split()[0] if job.status else ''  # Get first word of status
                if status_lower == 'pass':
                    pass_count += 1
                elif status_lower in ('fail', 'failed'):
                    fail_count += 1
                elif status_lower == 'running':
                    running_count += 1
                elif status_lower in ('queued', 'prep'):
                    queued_count += 1
                elif status_lower == 'killed':
                    killed_count += 1
        
        return ExperimentDetail(
            name=experiment_info.get('EXPERIMENT_NAME', ''),
            service=experiment_info.get('SERVICE', ''),
            cluster=experiment_info.get('CLUSTER', ''),
            workspace=experiment_info.get('WORKSPACE', ''),
            n_jobs=safe_int(experiment_info.get('N_JOBS', ''), len(jobs)),
            description=experiment_info.get('DESCRIPTION', ''),
            pass_count=pass_count,
            fail_count=fail_count,
            running_count=running_count,
            queued_count=queued_count,
            jobs=jobs,
        )


def get_experiments(n_recent: int = 50) -> List[ExperimentInfo]:
    """Get list of recent experiments."""
    parser = AmltParser()
    success, stdout, stderr = parser.run_amlt_command(
        ['amlt', 'list', '--most-recent', str(n_recent)]
    )
    if success:
        return parser.parse_list_output(stdout)
    return []


def get_experiment_status(exp_name: str) -> Optional[ExperimentDetail]:
    """Get detailed status of an experiment."""
    parser = AmltParser()
    success, stdout, stderr = parser.run_amlt_command(
        ['amlt', 'status', exp_name]
    )
    if success:
        return parser.parse_status_output(stdout)
    return None
