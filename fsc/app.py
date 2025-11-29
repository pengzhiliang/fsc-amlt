"""
FSC - Interactive TUI Application
A modern terminal-based AMLT job manager.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional, List, Dict
from dataclasses import dataclass, field

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen, ModalScreen
from textual.widgets import (
    Header, Footer, Static, Button, 
    ListView, ListItem, Rule, Log,
    LoadingIndicator, TabbedContent, TabPane, Input
)
from textual.reactive import reactive
from rich.text import Text

from .amlt_parser import get_experiments, get_experiment_status, AmltParser, ExperimentInfo, ExperimentDetail
from .cache import get_cache, ExperimentCache, TERMINAL_STATES, CachedExperimentDetail

# Try to import pyperclip for clipboard support
try:
    import pyperclip
    HAS_CLIPBOARD = True
except ImportError:
    HAS_CLIPBOARD = False


# Status styling - add 'killed' status
STATUS_DISPLAY = {
    'queued': ('◌', 'yellow', 'Queued'),
    'prep': ('◎', 'yellow', 'Preparing'),
    'running': ('●', 'cyan', 'Running'),
    'pass': ('✓', 'green', 'Passed'),
    'fail': ('✗', 'red', 'Failed'),
    'failed': ('✗', 'red', 'Failed'),
    'killed': ('⊘', 'magenta', 'Killed'),
    'cancelled': ('○', 'dim', 'Cancelled'),
    'unknown': ('?', 'dim', 'Unknown'),
}


def parse_time_ago(s: str) -> int:
    """
    Parse time ago string to minutes for sorting.
    E.g., "5m ago" -> 5, "2h ago" -> 120, "3d ago" -> 4320
    Lower value = more recent
    """
    if not s:
        return 999999
    s = s.strip().lower()
    match = re.match(r'(\d+)\s*(m|h|d|w)\s*ago', s)
    if match:
        val, unit = int(match.group(1)), match.group(2)
        if unit == 'm':
            return val
        elif unit == 'h':
            return val * 60
        elif unit == 'd':
            return val * 60 * 24
        elif unit == 'w':
            return val * 60 * 24 * 7
    return 999999


def parse_compound_status(status_str: str) -> Dict[str, int]:
    """
    Parse compound status like 'Running (12), Queued (2)' or 'Killed (16), Running (3), Pass (4)'
    Returns dict of status -> count
    """
    result = {}
    # Match patterns like "Running (12)" or "Pass (4)"
    pattern = r'(\w+)\s*\((\d+)\)'
    for match in re.finditer(pattern, status_str):
        status_type = match.group(1).lower()
        count = int(match.group(2))
        result[status_type] = count
    return result


def get_primary_status(status_str: str) -> str:
    """Get the primary status from a compound status string."""
    status_counts = parse_compound_status(status_str)
    if not status_counts:
        return status_str.lower()
    
    # Priority: running > queued > prep > fail > killed > pass
    priority = ['running', 'queued', 'prep', 'fail', 'failed', 'killed', 'pass']
    for s in priority:
        if s in status_counts:
            return s
    return list(status_counts.keys())[0]


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
    def from_info(cls, info: ExperimentInfo) -> 'ExpData':
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


class ExperimentListItem(ListItem):
    """A list item representing an experiment."""
    
    # Column widths for alignment
    COL_NAME = 22
    COL_STATUS = 16
    COL_FLAGS = 8
    COL_CLUSTER = 22
    COL_TIME = 10
    
    def __init__(self, exp: ExpData, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.exp = exp
    
    def _build_status_str(self, exp: ExpData) -> tuple[str, int]:
        """Build status string and return (formatted_str, display_width)."""
        if exp.job_count > 1:
            parts = []
            raw_parts = []  # For calculating width
            if exp.running_count > 0:
                parts.append(f"[cyan]●{exp.running_count}[/]")
                raw_parts.append(f"●{exp.running_count}")
            if exp.queued_count > 0:
                parts.append(f"[yellow]◌{exp.queued_count}[/]")
                raw_parts.append(f"◌{exp.queued_count}")
            if exp.pass_count > 0:
                parts.append(f"[green]✓{exp.pass_count}[/]")
                raw_parts.append(f"✓{exp.pass_count}")
            if exp.fail_count > 0:
                parts.append(f"[red]✗{exp.fail_count}[/]")
                raw_parts.append(f"✗{exp.fail_count}")
            if exp.killed_count > 0:
                parts.append(f"[magenta]⊘{exp.killed_count}[/]")
                raw_parts.append(f"⊘{exp.killed_count}")
            if parts:
                return " ".join(parts), len(" ".join(raw_parts))
            else:
                return f"[dim]{exp.job_count} jobs[/]", len(f"{exp.job_count} jobs")
        else:
            icon, color, _ = STATUS_DISPLAY.get(exp.status, ('?', 'white', exp.status))
            return f"[{color}]{icon}[/]", 1
    
    def compose(self) -> ComposeResult:
        exp = self.exp
        
        # Build status display
        status_str, status_width = self._build_status_str(exp)
        
        # Truncate long names
        name = exp.name[:self.COL_NAME-2] + ".." if len(exp.name) > self.COL_NAME else exp.name
        cluster = exp.cluster[:self.COL_CLUSTER-2] + ".." if len(exp.cluster) > self.COL_CLUSTER else exp.cluster
        
        # Format flags
        flags = exp.flags[:self.COL_FLAGS-2] + ".." if len(exp.flags) > self.COL_FLAGS else exp.flags
        
        # Pad status with spaces to align next column
        status_padding = " " * (self.COL_STATUS - status_width)
        
        # Format with fixed columns: name | status | cluster | flags | modified
        content = (
            f" [bold]{name:<{self.COL_NAME}}[/] "
            f"{status_str}{status_padding} "
            f"[dim]{cluster:<{self.COL_CLUSTER}}[/] "
            f"[cyan]{flags:<{self.COL_FLAGS}}[/] "
            f"[yellow]{exp.modified:>{self.COL_TIME}}[/]"
        )
        
        yield Static(content)


class JobListItem(ListItem):
    """A list item representing a job."""
    
    def __init__(self, job: JobData, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.job = job
    
    def compose(self) -> ComposeResult:
        job = self.job
        icon, color, _ = STATUS_DISPLAY.get(job.status.lower(), ('?', 'white', job.status))
        
        content = (
            f"  [dim]:{job.index:<3}[/]  "
            f"[bold]{job.name:<25}[/]  "
            f"[{color}]{icon} {job.status:<10}[/]  "
            f"[cyan]{job.duration or '-':<8}[/]  "
            f"[yellow]{job.submitted}[/]"
        )
        
        yield Static(content)


class NotificationBar(Static):
    """Shows status change notifications."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._notifications: List[StatusChange] = []
    
    def add_notification(self, change: StatusChange):
        """Add a new notification."""
        self._notifications.insert(0, change)
        self._notifications = self._notifications[:5]
        self._refresh_display()
    
    def clear(self):
        """Clear all notifications."""
        self._notifications = []
        self._refresh_display()
    
    def _refresh_display(self):
        """Refresh the notification display."""
        if not self._notifications:
            self.update("")
            self.display = False
            return
        
        self.display = True
        lines = []
        for n in self._notifications[:3]:
            old_icon, old_color, _ = STATUS_DISPLAY.get(n.old_status, ('?', 'dim', ''))
            new_icon, new_color, _ = STATUS_DISPLAY.get(n.new_status, ('?', 'dim', ''))
            time_str = n.timestamp.strftime("%H:%M:%S")
            lines.append(
                f"  [dim]{time_str}[/] [bold]{n.exp_name}[/]: "
                f"[{old_color}]{old_icon}[/] → [{new_color}]{new_icon}[/]"
            )
        
        self.update("\n".join(lines))


class ConfirmDialog(ModalScreen[bool]):
    """A confirmation dialog with double-check for dangerous operations."""
    
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]
    
    def __init__(self, message: str, action_name: str = "Confirm", confirm_text: str = ""):
        super().__init__()
        self.message = message
        self.action_name = action_name
        # Text user must type to confirm (for dangerous operations)
        self.confirm_text = confirm_text
        self.user_input = ""
    
    def compose(self) -> ComposeResult:
        with Container(id="dialog-container"):
            yield Static(f"[bold red]⚠️  WARNING ⚠️[/]\n\n{self.message}", id="dialog-message")
            if self.confirm_text:
                yield Static(f"\n[bold yellow]Type '[white]yes[/]' to confirm:[/]", id="dialog-hint")
                yield Input(placeholder="Type: yes", id="confirm-input")
            else:
                yield Static(f"\n[bold]Press [green]Y[/] to {self.action_name}, [red]N/Esc[/] to cancel[/]", id="dialog-hint")
    
    def on_mount(self):
        if self.confirm_text:
            self.query_one("#confirm-input").focus()
    
    def on_input_submitted(self, event):
        """Handle input submission for double-check."""
        if event.value.strip().lower() == 'yes':
            self.dismiss(True)
        else:
            self.query_one("#dialog-message", Static).update(
                f"[bold red]⚠️  MISMATCH ⚠️[/]\n\n{self.message}\n\n[red]Please type 'yes' to confirm.[/]"
            )
            event.input.value = ""
    
    def on_key(self, event):
        """Handle Y/N keys only if no confirm_text required."""
        if not self.confirm_text:
            if event.key == "y":
                self.dismiss(True)
            elif event.key == "n":
                self.dismiss(False)
    
    def action_cancel(self):
        self.dismiss(False)


def get_amlt_output_dir() -> str:
    """Get AMLT default output directory from cache."""
    from .cache import get_config_cache
    return get_config_cache().get_output_dir()


class JobLogScreen(Screen):
    """Screen showing job logs."""
    
    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("q", "go_back", "Back"),
        Binding("r", "refresh_logs", "Refresh"),
    ]
    
    def __init__(self, exp_name: str, job: JobData):
        super().__init__()
        self.exp_name = exp_name
        self.job = job
        self._output_dir = None
    
    def compose(self) -> ComposeResult:
        yield Header()
        
        with VerticalScroll():
            icon, color, _ = STATUS_DISPLAY.get(self.job.status.lower(), ('?', 'white', ''))
            yield Static(
                f"  [bold]{self.exp_name}[/] → [cyan]{self.job.name}[/]  "
                f"[{color}]{icon} {self.job.status}[/]  "
                f"Duration: [cyan]{self.job.duration or '-'}[/]",
                id="log-header"
            )
            yield Rule()
            yield Static("  [dim]Loading...[/]", id="log-status")
            yield Log(id="job-log", highlight=True, auto_scroll=True)
        
        yield Footer()
    
    def on_mount(self):
        self._load_logs()
    
    def _get_output_dir(self) -> str:
        """Get cached output dir."""
        if self._output_dir is None:
            self._output_dir = get_amlt_output_dir()
        return self._output_dir
    
    def _get_job_log_dir(self) -> str:
        """Get the directory for this specific job's logs."""
        import os
        # Use job index to ensure unique directory: {output_dir}/{exp_name}_job{index}/
        return os.path.join(self._get_output_dir(), f"{self.exp_name}_job{self.job.index}")
    
    def _get_log_path(self) -> str:
        """Get the local log file path for this job."""
        import os
        # Path: {job_log_dir}/{exp_name}/{job_name}/stdout.txt
        job_name = self.job.name.lstrip(':')
        return os.path.join(self._get_job_log_dir(), self.exp_name, job_name, "stdout.txt")
    
    def _find_log_file(self) -> str:
        """Find the log file, preferring latest retry logs."""
        import os
        import re
        
        job_log_dir = self._get_job_log_dir()
        if not os.path.isdir(job_log_dir):
            return ""
        
        # Collect all log files with their retry numbers
        log_files = []
        for root, dirs, files in os.walk(job_log_dir):
            for f in files:
                if f.endswith('.txt') and ('std_log' in f or f == 'stdout.txt'):
                    full_path = os.path.join(root, f)
                    # Check if it's in a retry directory
                    match = re.search(r'retry_(\d+)', root)
                    retry_num = int(match.group(1)) if match else -1
                    log_files.append((retry_num, full_path))
        
        if not log_files:
            return ""
        
        # Sort by retry number (highest first), return the latest
        log_files.sort(key=lambda x: x[0], reverse=True)
        return log_files[0][1]
    
    def _load_logs(self):
        """Load logs from local file or download first."""
        log_path = self._find_log_file()
        
        if log_path:
            self._display_local_logs(log_path)
        else:
            # Need to download first
            self._download_and_display()
    
    def _display_local_logs(self, log_path: str):
        """Display logs from local file."""
        status = self.query_one("#log-status", Static)
        log_widget = self.query_one("#job-log", Log)
        log_widget.clear()
        
        try:
            with open(log_path, 'r') as f:
                lines = f.readlines()
            
            # Show last 200 lines
            display_lines = lines[-200:] if len(lines) > 200 else lines
            status.update(f"  [dim]{log_path}[/]\n  [dim]Showing last {len(display_lines)} of {len(lines)} lines[/]")
            
            for line in display_lines:
                log_widget.write_line(line.rstrip())
        except Exception as e:
            status.update(f"  [red]Error: {e}[/]")
    
    def _get_latest_log_filename(self) -> str:
        """Get the latest log filename (handling retries) by listing available logs."""
        import subprocess
        import re
        
        cmd = ['amlt', 'logs', '--list', self.exp_name, f':{self.job.index}']
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                return ""
            
            # Parse output to find retry logs
            lines = result.stdout.strip().split('\n')
            
            # Look for user_logs/retry_XXX/std_log_process_0.txt pattern
            retry_logs = []
            for line in lines:
                line = line.strip()
                # Match patterns like: user_logs/retry_035/std_log_process_0.txt
                match = re.search(r'user_logs/retry_(\d+)/std_log_process_\d+\.txt', line)
                if match:
                    retry_num = int(match.group(1))
                    retry_logs.append((retry_num, line))
            
            if retry_logs:
                # Sort by retry number and get the latest
                retry_logs.sort(key=lambda x: x[0], reverse=True)
                return retry_logs[0][1]
            
            # No retry logs found, check for regular stdout
            # Look for std_log_process_0.txt without retry
            for line in lines:
                if 'std_log_process_0.txt' in line and 'retry' not in line:
                    return line.strip()
            
            return ""
        except Exception:
            return ""
    
    @work(thread=True)
    def _download_and_display(self):
        """Download logs using amlt to job-specific directory, getting latest retry."""
        import subprocess
        import os
        
        self.app.call_from_thread(
            lambda: self.query_one("#log-status", Static).update("  [yellow]Finding latest logs...[/]")
        )
        
        # First, find the latest log file (handling retries)
        latest_log = self._get_latest_log_filename()
        
        # Use -o to specify output directory for this specific job
        job_log_dir = self._get_job_log_dir()
        os.makedirs(job_log_dir, exist_ok=True)
        
        self.app.call_from_thread(
            lambda: self.query_one("#log-status", Static).update(
                f"  [yellow]Downloading: {latest_log or 'stdout'}...[/]"
            )
        )
        
        # Build command - use -F if we found a specific log file
        if latest_log:
            cmd = ['amlt', 'logs', '-F', latest_log, '-o', job_log_dir, self.exp_name, f':{self.job.index}']
        else:
            cmd = ['amlt', 'logs', '-o', job_log_dir, self.exp_name, f':{self.job.index}']
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                # Find the downloaded file
                log_path = self._find_log_file()
                if log_path:
                    self.app.call_from_thread(self._display_local_logs, log_path)
                else:
                    self.app.call_from_thread(
                        lambda: self.query_one("#log-status", Static).update(
                            f"  [yellow]Download completed but log file not found[/]\n  [dim]Dir: {job_log_dir}[/]"
                        )
                    )
            else:
                error_msg = result.stderr.strip() if result.stderr else "Unknown error"
                self.app.call_from_thread(
                    lambda: self.query_one("#log-status", Static).update(
                        f"  [red]Download failed: {error_msg}[/]\n  [dim]Command: {' '.join(cmd)}[/]"
                    )
                )
        except subprocess.TimeoutExpired:
            self.app.call_from_thread(
                lambda: self.query_one("#log-status", Static).update("  [red]Download timeout (120s)[/]")
            )
        except Exception as e:
            self.app.call_from_thread(
                lambda: self.query_one("#log-status", Static).update(f"  [red]Error: {e}[/]")
            )
    
    def action_go_back(self):
        self.app.pop_screen()
    
    def action_refresh_logs(self):
        """Refresh logs - download fresh and display."""
        self.query_one("#job-log", Log).clear()
        self._download_and_display()


class ExperimentDetailScreen(Screen):
    """Screen showing experiment details and jobs."""
    
    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("q", "go_back", "Back"),
        Binding("r", "refresh", "Refresh"),
        Binding("ctrl+k", "cancel_selected", "Cancel Job"),  # Changed from 'c' to avoid accidents
        Binding("ctrl+shift+k", "cancel_all", "Cancel All"),  # Changed from 'C' to avoid accidents
        Binding("enter", "view_logs", "View Logs"),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up", show=False),
    ]
    
    def __init__(self, exp: ExpData):
        super().__init__()
        self.exp = exp
        self.jobs: List[JobData] = []
    
    def compose(self) -> ComposeResult:
        yield Header()
        
        with VerticalScroll():
            yield Static(id="exp-info")
            yield Rule()
            yield Static("  [bold]Jobs[/]  [dim](Enter=Logs, Ctrl+K=Cancel, Ctrl+Shift+K=Cancel All)[/]")
            yield LoadingIndicator(id="detail-loading")
            yield ListView(id="jobs-list")
        
        yield Footer()
    
    def on_mount(self):
        self._fetch_details()
    
    @work(thread=True)
    def _fetch_details(self):
        """Fetch experiment details - use cache for terminal experiments."""
        from .cache import get_detail_cache
        
        self.app.call_from_thread(
            lambda: setattr(self.query_one("#detail-loading", LoadingIndicator), 'display', True)
        )
        
        # Check cache first
        detail_cache = get_detail_cache()
        cached = detail_cache.get(self.exp.name)
        
        if cached:
            # Use cached data
            self.app.call_from_thread(self._update_display_from_cache, cached)
            return
        
        # Fetch from API
        detail = get_experiment_status(self.exp.name)
        
        # Cache if terminal
        if detail and detail.jobs:
            detail_cache.add(self.exp.name, detail, detail.jobs)
        
        self.app.call_from_thread(self._update_display, detail)
    
    def _update_display_from_cache(self, cached: CachedExperimentDetail):
        """Update display from cached data."""
        self.query_one("#detail-loading", LoadingIndicator).display = False
        
        # Determine status
        if cached.running_count > 0:
            real_status = 'running'
        elif cached.queued_count > 0:
            real_status = 'queued'
        elif cached.fail_count > 0:
            real_status = 'fail'
        elif cached.killed_count > 0:
            real_status = 'killed'
        elif cached.pass_count > 0:
            real_status = 'pass'
        else:
            real_status = self.exp.status
        
        icon, color, status_name = STATUS_DISPLAY.get(real_status, ('?', 'white', real_status))
        
        info = (
            f"  [bold cyan]{cached.name}[/]  [dim](cached)[/]\n\n"
            f"  Status: [{color}]{icon} {status_name}[/]  |  "
            f"Cluster: [cyan]{cached.cluster}[/]  |  "
            f"Jobs: {cached.n_jobs}\n"
            f"  [green]✓ {cached.pass_count}[/]  "
            f"[cyan]● {cached.running_count}[/]  "
            f"[yellow]◌ {cached.queued_count}[/]  "
            f"[red]✗ {cached.fail_count}[/]  "
            f"[magenta]⊘ {cached.killed_count}[/]"
        )
        self.query_one("#exp-info", Static).update(info)
        
        # Update jobs list
        jobs_list = self.query_one("#jobs-list", ListView)
        jobs_list.clear()
        
        self.jobs = []
        for j in cached.jobs:
            job = JobData(
                index=j.index,
                name=j.name,
                status=j.status,
                duration=j.duration,
                size=j.size,
                submitted=j.submitted,
                flags=j.flags,
                portal_url=j.portal_url,
            )
            self.jobs.append(job)
            jobs_list.append(JobListItem(job))
    
    def _update_display(self, detail: Optional[ExperimentDetail]):
        """Update the display with fetched data."""
        self.query_one("#detail-loading", LoadingIndicator).display = False
        
        if not detail:
            self.query_one("#exp-info", Static).update("  [red]Failed to fetch details[/]")
            return
        
        # Get status from job :0 (parent job) for multi-job experiments
        def get_status(j) -> str:
            return j.status.lower().split()[0] if j.status else ''
        
        job0 = next((j for j in detail.jobs if j.index == 0), None)
        
        # Count job statuses for display
        real_pass = sum(1 for j in detail.jobs if get_status(j) == 'pass')
        real_fail = sum(1 for j in detail.jobs if get_status(j) in ('fail', 'failed'))
        real_running = sum(1 for j in detail.jobs if get_status(j) == 'running')
        real_queued = sum(1 for j in detail.jobs if get_status(j) in ('queued', 'prep'))
        real_killed = sum(1 for j in detail.jobs if get_status(j) == 'killed')
        
        # For multi-job experiments, use job :0's status as the overall status
        if job0 and len(detail.jobs) > 1:
            real_status = get_status(job0)
            if real_status in ('fail', 'failed'):
                real_status = 'fail'
        else:
            # Single job or no job :0 - use aggregated status
            if real_running > 0:
                real_status = 'running'
            elif real_queued > 0:
                real_status = 'queued'
            elif real_fail > 0:
                real_status = 'fail'
            elif real_killed > 0:
                real_status = 'killed'
            elif real_pass > 0:
                real_status = 'pass'
            else:
                real_status = self.exp.status
        
        # If determined to be terminal, update both caches
        if real_status in TERMINAL_STATES:
            from .cache import get_cache, get_detail_cache
            # Update experiment cache with correct status
            exp_cache = get_cache()
            exp_cache.force_add(
                name=self.exp.name,
                status=real_status,
                cluster=detail.cluster,
                job_count=detail.n_jobs,
                pass_count=real_pass,
                fail_count=real_fail,
                killed_count=real_killed,
            )
            # Also cache the detail
            detail_cache = get_detail_cache()
            detail_cache.add(self.exp.name, detail, detail.jobs)
        
        icon, color, status_name = STATUS_DISPLAY.get(real_status, ('?', 'white', real_status))
        
        info = (
            f"  [bold cyan]{self.exp.name}[/]\n\n"
            f"  Status: [{color}]{icon} {status_name}[/]  |  "
            f"Cluster: [cyan]{detail.cluster}[/]  |  "
            f"Jobs: {detail.n_jobs}\n"
            f"  [green]✓ {real_pass}[/]  "
            f"[cyan]● {real_running}[/]  "
            f"[yellow]◌ {real_queued}[/]  "
            f"[red]✗ {real_fail}[/]  "
            f"[magenta]⊘ {real_killed}[/]"
        )
        self.query_one("#exp-info", Static).update(info)
        
        # Update jobs list (sorted by submitted time, newest first)
        jobs_list = self.query_one("#jobs-list", ListView)
        jobs_list.clear()
        
        self.jobs = []
        for job_info in detail.jobs:
            job = JobData(
                index=job_info.index,
                name=job_info.name,
                status=job_info.status.split()[0] if job_info.status else '',  # Get first word
                duration=job_info.duration,
                size=job_info.size,
                submitted=job_info.submitted,
                flags=job_info.flags,
                portal_url=job_info.portal_url,
            )
            self.jobs.append(job)
        
        # Sort by submitted time (newest first)
        self.jobs.sort(key=lambda j: parse_time_ago(j.submitted))
        
        for job in self.jobs:
            jobs_list.append(JobListItem(job))
    
    def action_go_back(self):
        self.app.pop_screen()
    
    def action_refresh(self):
        self._fetch_details()
    
    def action_view_logs(self):
        """View logs for selected job."""
        jobs_list = self.query_one("#jobs-list", ListView)
        if jobs_list.index is not None and jobs_list.index < len(self.jobs):
            job = self.jobs[jobs_list.index]
            self.app.push_screen(JobLogScreen(self.exp.name, job))
    
    def action_cancel_selected(self):
        """Cancel selected job - requires typing job name to confirm."""
        jobs_list = self.query_one("#jobs-list", ListView)
        if jobs_list.index is not None and jobs_list.index < len(self.jobs):
            job = self.jobs[jobs_list.index]
            if job.status.lower() in ('running', 'queued', 'prep'):
                # Extract short name for confirmation (remove : prefix if present)
                confirm_name = job.name.lstrip(':')
                self.app.push_screen(
                    ConfirmDialog(
                        f"Cancel job [bold cyan]{job.name}[/] in [bold]{self.exp.name}[/]?",
                        "Cancel",
                        confirm_text=confirm_name  # User must type job name to confirm
                    ),
                    callback=lambda result: self._do_cancel_job(job) if result else None
                )
            else:
                self.notify(f"Job {job.name} is not active (status: {job.status})", severity="warning")
    
    def action_cancel_all(self):
        """Cancel all running jobs - requires typing experiment name to confirm."""
        active_jobs = [j for j in self.jobs if j.status.lower() in ('running', 'queued', 'prep')]
        if active_jobs:
            self.app.push_screen(
                ConfirmDialog(
                    f"[bold red]DANGER:[/] Cancel ALL [bold]{len(active_jobs)}[/] active jobs in [bold cyan]{self.exp.name}[/]?",
                    "Cancel All",
                    confirm_text=self.exp.name  # User must type experiment name to confirm
                ),
                callback=lambda result: self._do_cancel_all() if result else None
            )
        else:
            self.notify("No active jobs to cancel", severity="warning")
    
    @work(thread=True)
    def _do_cancel_job(self, job: JobData):
        """Cancel a specific job."""
        parser = AmltParser()
        success, _, stderr = parser.run_amlt_command([
            'amlt', 'cancel', '-y', self.exp.name, f':{job.index}'
        ])
        
        if success:
            self.app.call_from_thread(self._fetch_details)
            self.app.call_from_thread(lambda: self.notify(f"Cancelled {job.name}"))
        else:
            self.app.call_from_thread(lambda: self.notify(f"Failed: {stderr}", severity="error"))
    
    @work(thread=True)
    def _do_cancel_all(self):
        """Cancel all jobs."""
        parser = AmltParser()
        success, _, stderr = parser.run_amlt_command(['amlt', 'cancel', '-y', self.exp.name])
        
        if success:
            self.app.call_from_thread(self._fetch_details)
            self.app.call_from_thread(lambda: self.notify(f"Cancelled all jobs"))
        else:
            self.app.call_from_thread(lambda: self.notify(f"Failed: {stderr}", severity="error"))
    
    def action_cursor_down(self):
        self.query_one("#jobs-list", ListView).action_cursor_down()
    
    def action_cursor_up(self):
        self.query_one("#jobs-list", ListView).action_cursor_up()


class MainScreen(Screen):
    """Main screen showing experiments grouped by status."""
    
    BINDINGS = [
        Binding("enter", "select_experiment", "Open", priority=True),
        Binding("r", "refresh", "Refresh"),
        Binding("y", "copy_name", "Copy"),
        Binding("ctrl+k", "cancel_experiment", "Cancel"),
        Binding("n", "clear_notifications", "Clear"),
        Binding("q", "quit", "Quit"),
        Binding("1", "tab_running", "Running", show=False),
        Binding("2", "tab_queued", "Queued", show=False),
        Binding("3", "tab_passed", "Passed", show=False),
        Binding("4", "tab_failed", "Failed", show=False),
        Binding("5", "tab_killed", "Killed", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up", show=False),
    ]
    
    def __init__(self):
        super().__init__()
        self.all_experiments: List[ExpData] = []
        self.grouped: Dict[str, List[ExpData]] = {}
        self.last_statuses: Dict[str, str] = {}
    
    def compose(self) -> ComposeResult:
        yield Header()
        
        with Container(id="main-container"):
            yield NotificationBar(id="notifications")
            yield Static(id="summary-bar")
            
            with TabbedContent(id="tabs", initial="tab-queued"):
                with TabPane("◌ Queued", id="tab-queued"):
                    yield ListView(id="list-queued")
                with TabPane("● Running", id="tab-running"):
                    yield ListView(id="list-running")
                with TabPane("✓ Passed", id="tab-passed"):
                    yield ListView(id="list-passed")
                with TabPane("✗ Failed", id="tab-failed"):
                    yield ListView(id="list-failed")
                with TabPane("⊘ Killed", id="tab-killed"):
                    yield ListView(id="list-killed")
            
            yield LoadingIndicator(id="main-loading")
        
        yield Footer()
    
    def on_mount(self):
        self.query_one("#notifications", NotificationBar).display = False
        self.cache = get_cache()
        self._fetch_experiments()
        self.set_interval(300, self._fetch_experiments)
        # Start background status correction for active experiments (every 5 minutes)
        self.set_interval(300, self._correct_active_statuses)
    
    @work(thread=True)
    def _fetch_experiments(self):
        """Fetch experiments in background thread."""
        self.app.call_from_thread(
            lambda: setattr(self.query_one("#main-loading", LoadingIndicator), 'display', True)
        )
        
        # Get fresh data from API
        exp_infos = get_experiments(n_recent=50)
        
        # Also load cached terminal experiments
        cached_exps = self.cache.get_all()
        
        self.app.call_from_thread(self._update_display, exp_infos, cached_exps)

    @work(thread=True, exclusive=True, name="correct_status")
    def _correct_active_statuses(self):
        """
        Background task to correct status of active experiments.
        Fetches detailed status for running/queued experiments and updates cache.
        For multi-job experiments, uses job :0 status to determine overall status.
        """
        # Get active experiments from current display
        active_exps = []
        for status in ('running', 'queued'):
            if status in self.grouped:
                active_exps.extend(self.grouped[status])
        
        if not active_exps:
            return
        
        # Limit to avoid too many API calls
        active_exps = active_exps[:10]
        total = len(active_exps)
        
        corrections = []  # List of (exp_name, old_status, new_status, detail)
        
        for i, exp in enumerate(active_exps):
            detail = get_experiment_status(exp.name)
            if not detail or not detail.jobs:
                continue
            
            # Determine real status based on job :0 for multi-job experiments
            if len(detail.jobs) > 1:
                # Find job :0
                job0 = next((j for j in detail.jobs if j.index == 0), None)
                if job0:
                    job0_status = job0.status.lower().split()[0] if job0.status else ''
                    # Map job status to experiment status
                    if job0_status in ('pass', 'fail', 'failed', 'killed'):
                        new_status = job0_status if job0_status != 'failed' else 'fail'
                        if exp.status != new_status:
                            corrections.append((exp.name, exp.status, new_status, detail))
            else:
                # Single job - use its status directly
                job_status = detail.jobs[0].status.lower().split()[0] if detail.jobs[0].status else ''
                if job_status in ('pass', 'fail', 'failed', 'killed'):
                    new_status = job_status if job_status != 'failed' else 'fail'
                    if exp.status != new_status:
                        corrections.append((exp.name, exp.status, new_status, detail))
        
        # Apply corrections if any
        if corrections:
            self.app.call_from_thread(self._apply_status_corrections, corrections)
    
    def _apply_status_corrections(self, corrections):
        """Apply status corrections and update display."""
        notifications = self.query_one("#notifications", NotificationBar)
        
        for exp_name, old_status, new_status, detail in corrections:
            # Update cache (force_add only accepts terminal state fields)
            self.cache.force_add(
                name=exp_name,
                status=new_status,
                cluster=detail.cluster,
                job_count=detail.n_jobs,
                pass_count=detail.pass_count,
                fail_count=detail.fail_count,
                killed_count=len([j for j in detail.jobs if j.status.lower().split()[0] == 'killed']),
            )
            
            # Show notification
            notifications.add_notification(StatusChange(
                exp_name=exp_name,
                old_status=old_status,
                new_status=new_status
            ))
            notifications.display = True
        
        # Refresh display
        self._fetch_experiments()

    def _update_display(self, exp_infos: List[ExperimentInfo], cached_exps=None):
        """Update experiments display."""
        self.query_one("#main-loading", LoadingIndicator).display = False
        
        notifications = self.query_one("#notifications", NotificationBar)
        
        # Track which experiments we've seen from API
        api_exp_names = set()
        
        # Convert API results to ExpData and detect changes
        self.all_experiments = []
        for info in exp_infos:
            exp = ExpData.from_info(info)
            self.all_experiments.append(exp)
            api_exp_names.add(exp.name)
            
            # Cache terminal experiments
            if exp.is_terminal():
                self.cache.add_from_exp_data(exp)
            
            # Check for status changes
            old_status = self.last_statuses.get(exp.name)
            if old_status and old_status != exp.status:
                notifications.add_notification(StatusChange(
                    exp_name=exp.name,
                    old_status=old_status,
                    new_status=exp.status
                ))
            self.last_statuses[exp.name] = exp.status
        
        # Add cached experiments that weren't in the API response
        # (older terminal experiments that fell off the --most-recent list)
        if cached_exps:
            for cached in cached_exps:
                if cached.name not in api_exp_names:
                    exp = ExpData.from_cached(cached)
                    self.all_experiments.append(exp)
        
        # Group by status
        self.grouped = {
            'running': [],
            'queued': [],
            'pass': [],
            'fail': [],
            'killed': [],
        }
        
        for exp in self.all_experiments:
            status = exp.status
            if status == 'running':
                self.grouped['running'].append(exp)
            elif status in ('queued', 'prep'):
                self.grouped['queued'].append(exp)
            elif status == 'pass':
                self.grouped['pass'].append(exp)
            elif status in ('fail', 'failed'):
                self.grouped['fail'].append(exp)
            elif status == 'killed':
                self.grouped['killed'].append(exp)
        
        # Sort each group by modified time (most recent first)
        for status in self.grouped:
            self.grouped[status].sort(key=lambda e: parse_time_ago(e.modified))
        
        # Count cached experiments
        cached_count = sum(1 for e in self.all_experiments if e.from_cache)
        
        # Update summary
        summary = (
            f"  [cyan bold]● {len(self.grouped['running'])} Running[/]  "
            f"[yellow]◌ {len(self.grouped['queued'])} Queued[/]  "
            f"[green]✓ {len(self.grouped['pass'])} Passed[/]  "
            f"[red]✗ {len(self.grouped['fail'])} Failed[/]  "
            f"[magenta]⊘ {len(self.grouped['killed'])} Killed[/]  "
            f"[dim]| {datetime.now().strftime('%H:%M:%S')}"
        )
        if cached_count > 0:
            summary += f" | 💾{cached_count} cached"
        summary += "[/]"
        self.query_one("#summary-bar", Static).update(summary)
        
        # Update lists
        for status, list_id in [
            ('running', 'list-running'),
            ('queued', 'list-queued'),
            ('pass', 'list-passed'),
            ('fail', 'list-failed'),
            ('killed', 'list-killed'),
        ]:
            list_view = self.query_one(f"#{list_id}", ListView)
            list_view.clear()
            for exp in self.grouped[status]:
                list_view.append(ExperimentListItem(exp))
    
    def _get_current_list(self) -> tuple[ListView, List[ExpData]]:
        """Get the currently active list and its experiments."""
        tabs = self.query_one("#tabs", TabbedContent)
        active = tabs.active
        
        mapping = {
            "tab-running": ("list-running", 'running'),
            "tab-queued": ("list-queued", 'queued'),
            "tab-passed": ("list-passed", 'pass'),
            "tab-failed": ("list-failed", 'fail'),
            "tab-killed": ("list-killed", 'killed'),
        }
        
        if active in mapping:
            list_id, status = mapping[active]
            return self.query_one(f"#{list_id}", ListView), self.grouped.get(status, [])
        
        return self.query_one("#list-running", ListView), []
    
    def action_refresh(self):
        self._fetch_experiments()
        # Also trigger status correction if on queued or running tab
        tabs = self.query_one("#tabs", TabbedContent)
        if tabs.active in ("tab-queued", "tab-running"):
            self._correct_active_statuses()
    
    def action_select_experiment(self):
        """Open selected experiment."""
        list_view, experiments = self._get_current_list()
        if list_view.index is not None and list_view.index < len(experiments):
            exp = experiments[list_view.index]
            self.app.push_screen(ExperimentDetailScreen(exp))
    
    def action_cancel_experiment(self):
        """Cancel selected experiment - requires typing experiment name to confirm."""
        list_view, experiments = self._get_current_list()
        if list_view.index is not None and list_view.index < len(experiments):
            exp = experiments[list_view.index]
            if exp.status in ('running', 'queued', 'prep'):
                self.app.push_screen(
                    ConfirmDialog(
                        f"[bold red]DANGER:[/] Cancel experiment [bold cyan]{exp.name}[/]?\n\nThis will kill ALL jobs in this experiment!",
                        "Cancel",
                        confirm_text=exp.name  # User must type experiment name to confirm
                    ),
                    callback=lambda result: self._do_cancel(exp) if result else None
                )
            else:
                self.notify(f"Experiment {exp.name} is not active (status: {exp.status})", severity="warning")
    
    @work(thread=True)
    def _do_cancel(self, exp: ExpData):
        """Cancel an experiment."""
        parser = AmltParser()
        success, stdout, stderr = parser.run_amlt_command(['amlt', 'cancel', '-y', exp.name])
        if success:
            self.app.call_from_thread(self._fetch_experiments)
            self.app.call_from_thread(lambda: self.notify(f"✓ Cancelled {exp.name}"))
        else:
            error_msg = stderr or stdout or "Unknown error"
            self.app.call_from_thread(
                lambda: self.notify(f"✗ Failed to cancel {exp.name}: {error_msg[:100]}", severity="error")
            )
    
    def action_copy_name(self):
        """Copy selected experiment name to clipboard."""
        list_view, experiments = self._get_current_list()
        if list_view.index is not None and list_view.index < len(experiments):
            exp = experiments[list_view.index]
            if HAS_CLIPBOARD:
                try:
                    pyperclip.copy(exp.name)
                    self.notify(f"📋 Copied: {exp.name}", timeout=2)
                except Exception as e:
                    self.notify(f"Failed to copy: {e}", severity="error")
            else:
                # Fallback: show the name so user can manually copy
                self.notify(f"📋 {exp.name} (install pyperclip for clipboard)", timeout=5)
    
    def action_clear_notifications(self):
        self.query_one("#notifications", NotificationBar).clear()
    
    def action_cursor_down(self):
        list_view, _ = self._get_current_list()
        list_view.action_cursor_down()
    
    def action_cursor_up(self):
        list_view, _ = self._get_current_list()
        list_view.action_cursor_up()
    
    def action_tab_running(self):
        self.query_one("#tabs", TabbedContent).active = "tab-running"
    
    def action_tab_queued(self):
        self.query_one("#tabs", TabbedContent).active = "tab-queued"
    
    def action_tab_passed(self):
        self.query_one("#tabs", TabbedContent).active = "tab-passed"
    
    def action_tab_failed(self):
        self.query_one("#tabs", TabbedContent).active = "tab-failed"
    
    def action_tab_killed(self):
        self.query_one("#tabs", TabbedContent).active = "tab-killed"


class FSCApp(App):
    """The main FSC application."""
    
    CSS = """
    Screen {
        background: $surface;
    }
    
    #main-container {
        height: 100%;
    }
    
    #notifications {
        height: auto;
        max-height: 4;
        background: $primary-background;
        padding: 0;
    }
    
    #summary-bar {
        height: 1;
        background: $primary-background-darken-1;
    }
    
    #tabs {
        height: 1fr;
    }
    
    TabPane {
        padding: 0;
    }
    
    ListView {
        height: 1fr;
    }
    
    ListItem {
        padding: 0;
        height: 1;
    }
    
    ListItem:hover {
        background: $primary-background;
    }
    
    ListItem.-highlight {
        background: $primary;
    }
    
    LoadingIndicator {
        height: 3;
    }
    
    #dialog-container {
        align: center middle;
        width: 50;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: solid $primary;
    }
    
    #dialog-message {
        text-align: center;
        padding: 1;
    }
    
    #dialog-hint {
        text-align: center;
    }
    
    #log-header {
        height: 2;
        background: $primary-background;
    }
    
    #job-log {
        height: 1fr;
        border: solid $primary;
        margin: 1;
    }
    
    #exp-info {
        height: auto;
        padding: 1;
        background: $primary-background;
    }
    
    #jobs-list {
        height: 1fr;
    }
    """
    
    TITLE = "FSC - Fuck Smart Card"
    SUB_TITLE = "AMLT Job Manager"
    
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("?", "help", "Help"),
    ]
    
    def on_mount(self):
        self.push_screen(MainScreen())
    
    def action_help(self):
        """Show help."""
        self.notify(
            "↑↓/jk=Navigate | Enter=Open | r=Refresh | c=Cancel | 1-5=Tabs | q=Quit",
            timeout=5
        )


def run_app():
    """Run the FSC application."""
    app = FSCApp()
    app.run()


if __name__ == "__main__":
    run_app()
