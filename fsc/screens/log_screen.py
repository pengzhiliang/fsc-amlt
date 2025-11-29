"""
Job log viewing screen.
"""

from __future__ import annotations

import os
import re

from textual import work
from textual.app import ComposeResult
from textual.screen import Screen
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Header, Footer, Static, Rule, Log

from ..data import JobData
from ..utils import STATUS_DISPLAY, format_time_ago, get_amlt_output_dir


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
        return os.path.join(self._get_output_dir(), f"{self.exp_name}_job{self.job.index}")
    
    def _get_log_path(self) -> str:
        """Get the local log file path for this job."""
        job_name = self.job.name.lstrip(':')
        return os.path.join(self._get_job_log_dir(), self.exp_name, job_name, "stdout.txt")
    
    def _find_log_file(self) -> str:
        """Find the log file, preferring latest retry logs."""
        job_log_dir = self._get_job_log_dir()
        if not os.path.isdir(job_log_dir):
            return ""
        
        log_files = []
        for root, dirs, files in os.walk(job_log_dir):
            for f in files:
                if f.endswith('.txt') and ('std_log' in f or f == 'stdout.txt'):
                    full_path = os.path.join(root, f)
                    match = re.search(r'retry_(\d+)', root)
                    retry_num = int(match.group(1)) if match else -1
                    log_files.append((retry_num, full_path))
        
        if not log_files:
            return ""
        
        log_files.sort(key=lambda x: x[0], reverse=True)
        return log_files[0][1]
    
    def _load_logs(self):
        """Load logs - auto refresh for running jobs, use cache for others."""
        if self.job.status.lower() == 'running':
            self._download_and_display()
            return
        
        log_path = self._find_log_file()
        
        if log_path:
            self._display_local_logs(log_path)
        else:
            self._download_and_display()
    
    def _display_local_logs(self, log_path: str):
        """Display logs from local file."""
        status = self.query_one("#log-status", Static)
        log_widget = self.query_one("#job-log", Log)
        log_widget.clear()
        
        try:
            mtime = os.path.getmtime(log_path)
            time_ago = format_time_ago(mtime)
            
            with open(log_path, 'r') as f:
                lines = f.readlines()
            
            display_lines = lines[-200:] if len(lines) > 200 else lines
            status.update(f"  [dim]{log_path}[/]\n  [dim]Showing last {len(display_lines)} of {len(lines)} lines | cached {time_ago}[/]")
            
            for line in display_lines:
                log_widget.write_line(line.rstrip())
        except Exception as e:
            status.update(f"  [red]Error: {e}[/]")
    
    def _get_latest_log_filename(self) -> str:
        """Get the latest log filename by listing available logs."""
        import subprocess
        
        cmd = ['amlt', 'logs', '--list', self.exp_name, f':{self.job.index}']
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                return ""
            
            lines = result.stdout.strip().split('\n')
            retry_logs = []
            for line in lines:
                line = line.strip()
                match = re.search(r'user_logs/retry_(\d+)/std_log_process_\d+\.txt', line)
                if match:
                    retry_num = int(match.group(1))
                    retry_logs.append((retry_num, line))
            
            if retry_logs:
                retry_logs.sort(key=lambda x: x[0], reverse=True)
                return retry_logs[0][1]
            
            for line in lines:
                if 'std_log_process_0.txt' in line and 'retry' not in line:
                    return line.strip()
            
            return ""
        except Exception:
            return ""
    
    @work(thread=True)
    def _download_and_display(self):
        """Download logs using amlt to job-specific directory."""
        import subprocess
        
        self.app.call_from_thread(
            lambda: self.query_one("#log-status", Static).update("  [yellow]Finding latest logs...[/]")
        )
        
        latest_log = self._get_latest_log_filename()
        job_log_dir = self._get_job_log_dir()
        os.makedirs(job_log_dir, exist_ok=True)
        
        self.app.call_from_thread(
            lambda: self.query_one("#log-status", Static).update(
                f"  [yellow]Downloading: {latest_log or 'stdout'}...[/]"
            )
        )
        
        if latest_log:
            cmd = ['amlt', 'logs', '-F', latest_log, '-o', job_log_dir, self.exp_name, f':{self.job.index}']
        else:
            cmd = ['amlt', 'logs', '-o', job_log_dir, self.exp_name, f':{self.job.index}']
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
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
