"""
Experiment detail screen showing jobs grouped by status.
"""

from __future__ import annotations

from typing import Optional, List, Dict

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Header, Footer, Static, ListView, LoadingIndicator, TabbedContent, TabPane

from .base import TabbedListScreen
from .log_screen import JobLogScreen
from ..data import ExpData, JobData
from ..cache import TERMINAL_STATES, CachedExperimentDetail
from ..utils import STATUS_DISPLAY, parse_time_ago, normalize_status
from ..widgets import JobListItem, ConfirmDialog
from ..amlt_parser import get_experiment_status, AmltParser, ExperimentDetail


class ExperimentDetailScreen(TabbedListScreen):
    """Screen showing experiment details and jobs grouped by status."""
    
    TABS_ID = "job-tabs"
    TAB_MAPPING = {
        "tab-running": ("list-running", 'running'),
        "tab-queued": ("list-queued", 'queued'),
        "tab-passed": ("list-passed", 'pass'),
        "tab-failed": ("list-failed", 'fail'),
        "tab-killed": ("list-killed", 'killed'),
    }
    
    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("q", "go_back", "Back"),
        Binding("r", "refresh", "Refresh"),
        Binding("ctrl+k", "cancel_selected", "Cancel Job"),
        Binding("ctrl+shift+k", "cancel_all", "Cancel All"),
        Binding("enter", "view_logs", "View Logs"),
        *TabbedListScreen.COMMON_BINDINGS,
    ]
    
    def __init__(self, exp: ExpData):
        super().__init__()
        self.exp = exp
        self.jobs: List[JobData] = []
        self.grouped_jobs: Dict[str, List[JobData]] = {}
        self._tab_order = ["tab-running", "tab-queued", "tab-passed", "tab-failed", "tab-killed"]
    
    def _get_data_for_status(self, status: str) -> List[JobData]:
        return self.grouped_jobs.get(status, [])
    
    def compose(self) -> ComposeResult:
        yield Header()
        
        with Container(id="detail-container"):
            yield Static(id="exp-info")
            yield LoadingIndicator(id="detail-loading")
            
            with TabbedContent(id="job-tabs", initial="tab-running"):
                with TabPane("● Running", id="tab-running"):
                    yield ListView(id="list-running")
                with TabPane("◌ Queued", id="tab-queued"):
                    yield ListView(id="list-queued")
                with TabPane("✓ Passed", id="tab-passed"):
                    yield ListView(id="list-passed")
                with TabPane("✗ Failed", id="tab-failed"):
                    yield ListView(id="list-failed")
                with TabPane("⊘ Killed", id="tab-killed"):
                    yield ListView(id="list-killed")
        
        yield Footer()
    
    def on_mount(self):
        self._fetch_details()
    
    def _get_initial_tab(self) -> str:
        """Determine which tab to show initially based on job counts."""
        if self.grouped_jobs.get('running'):
            return "tab-running"
        elif self.grouped_jobs.get('queued'):
            return "tab-queued"
        elif self.grouped_jobs.get('fail'):
            return "tab-failed"
        elif self.grouped_jobs.get('killed'):
            return "tab-killed"
        elif self.grouped_jobs.get('pass'):
            return "tab-passed"
        return "tab-running"
    
    def _group_jobs(self):
        """Group jobs by status."""
        self.grouped_jobs = {
            'running': [],
            'queued': [],
            'pass': [],
            'fail': [],
            'killed': [],
        }
        
        for job in self.jobs:
            status = normalize_status(job.status)
            if status == 'running':
                self.grouped_jobs['running'].append(job)
            elif status in ('queued', 'prep'):
                self.grouped_jobs['queued'].append(job)
            elif status == 'pass':
                self.grouped_jobs['pass'].append(job)
            elif status in ('fail', 'failed'):
                self.grouped_jobs['fail'].append(job)
            elif status == 'killed':
                self.grouped_jobs['killed'].append(job)
    
    def _update_job_lists(self):
        """Update all job list views."""
        for status, list_id in [
            ('running', 'list-running'),
            ('queued', 'list-queued'),
            ('pass', 'list-passed'),
            ('fail', 'list-failed'),
            ('killed', 'list-killed'),
        ]:
            list_view = self.query_one(f"#{list_id}", ListView)
            list_view.clear()
            jobs = self.grouped_jobs.get(status, [])
            jobs.sort(key=lambda j: parse_time_ago(j.submitted))
            for job in jobs:
                list_view.append(JobListItem(job))
    
    @work(thread=True)
    def _fetch_details(self):
        """Fetch experiment details - use cache for terminal experiments."""
        from ..cache import get_detail_cache
        
        self.app.call_from_thread(
            lambda: setattr(self.query_one("#detail-loading", LoadingIndicator), 'display', True)
        )
        
        detail_cache = get_detail_cache()
        cached = detail_cache.get(self.exp.name)
        
        if cached:
            self.app.call_from_thread(self._update_display_from_cache, cached)
            return
        
        detail = get_experiment_status(self.exp.name)
        
        if detail and detail.jobs:
            detail_cache.add(self.exp.name, detail, detail.jobs)
        
        self.app.call_from_thread(self._update_display, detail)
    
    def _update_display_from_cache(self, cached: CachedExperimentDetail):
        """Update display from cached data."""
        self.query_one("#detail-loading", LoadingIndicator).display = False
        
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
        
        self._group_jobs()
        
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
            f"  [bold cyan]{cached.name}[/]  [dim](cached)[/]\n"
            f"  Status: [{color}]{icon} {status_name}[/]  |  "
            f"Cluster: [cyan]{cached.cluster}[/]  |  "
            f"Jobs: {cached.n_jobs}\n"
            f"  [cyan]● {len(self.grouped_jobs['running'])}[/]  "
            f"[yellow]◌ {len(self.grouped_jobs['queued'])}[/]  "
            f"[green]✓ {len(self.grouped_jobs['pass'])}[/]  "
            f"[red]✗ {len(self.grouped_jobs['fail'])}[/]  "
            f"[magenta]⊘ {len(self.grouped_jobs['killed'])}[/]"
        )
        self.query_one("#exp-info", Static).update(info)
        
        self._update_job_lists()
        self.query_one("#job-tabs", TabbedContent).active = self._get_initial_tab()
    
    def _update_display(self, detail: Optional[ExperimentDetail]):
        """Update the display with fetched data."""
        self.query_one("#detail-loading", LoadingIndicator).display = False
        
        if not detail:
            self.query_one("#exp-info", Static).update("  [red]Failed to fetch details[/]")
            return
        
        self.jobs = []
        for job_info in detail.jobs:
            job = JobData(
                index=job_info.index,
                name=job_info.name,
                status=job_info.status.split()[0] if job_info.status else '',
                duration=job_info.duration,
                size=job_info.size,
                submitted=job_info.submitted,
                flags=job_info.flags,
                portal_url=job_info.portal_url,
            )
            self.jobs.append(job)
        
        self._group_jobs()
        
        job0 = next((j for j in self.jobs if j.index == 0), None)
        
        real_running = len(self.grouped_jobs['running'])
        real_queued = len(self.grouped_jobs['queued'])
        real_pass = len(self.grouped_jobs['pass'])
        real_fail = len(self.grouped_jobs['fail'])
        real_killed = len(self.grouped_jobs['killed'])
        
        if job0 and len(self.jobs) > 1:
            real_status = normalize_status(job0.status)
        else:
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
        
        if real_status in TERMINAL_STATES:
            from ..cache import get_cache, get_detail_cache
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
            detail_cache = get_detail_cache()
            detail_cache.add(self.exp.name, detail, detail.jobs)
        
        icon, color, status_name = STATUS_DISPLAY.get(real_status, ('?', 'white', real_status))
        
        info = (
            f"  [bold cyan]{self.exp.name}[/]\n"
            f"  Status: [{color}]{icon} {status_name}[/]  |  "
            f"Cluster: [cyan]{detail.cluster}[/]  |  "
            f"Jobs: {detail.n_jobs}\n"
            f"  [cyan]● {real_running}[/]  "
            f"[yellow]◌ {real_queued}[/]  "
            f"[green]✓ {real_pass}[/]  "
            f"[red]✗ {real_fail}[/]  "
            f"[magenta]⊘ {real_killed}[/]"
        )
        self.query_one("#exp-info", Static).update(info)
        
        self._update_job_lists()
        self.query_one("#job-tabs", TabbedContent).active = self._get_initial_tab()
    
    def action_go_back(self):
        self.app.pop_screen()
    
    def action_refresh(self):
        from ..cache import get_detail_cache
        get_detail_cache().remove(self.exp.name)
        self._fetch_details()
    
    def action_view_logs(self):
        """View logs for selected job."""
        list_view, jobs = self._get_current_list()
        if list_view.index is not None and list_view.index < len(jobs):
            job = jobs[list_view.index]
            self.app.push_screen(JobLogScreen(self.exp.name, job))
    
    def action_cancel_selected(self):
        """Cancel selected job - requires typing 'yes' to confirm."""
        list_view, jobs = self._get_current_list()
        if list_view.index is not None and list_view.index < len(jobs):
            job = jobs[list_view.index]
            if job.status.lower() in ('running', 'queued', 'prep'):
                self.app.push_screen(
                    ConfirmDialog(
                        f"Cancel job [bold cyan]{job.name}[/] in [bold]{self.exp.name}[/]?",
                        "Cancel",
                        require_yes=True
                    ),
                    callback=lambda result: self._do_cancel_job(job) if result else None
                )
            else:
                self.notify(f"Job {job.name} is not active (status: {job.status})", severity="warning")
    
    def action_cancel_all(self):
        """Cancel all running jobs - requires typing 'yes' to confirm."""
        active_jobs = self.grouped_jobs.get('running', []) + self.grouped_jobs.get('queued', [])
        if active_jobs:
            self.app.push_screen(
                ConfirmDialog(
                    f"[bold red]DANGER:[/] Cancel ALL [bold]{len(active_jobs)}[/] active jobs in [bold cyan]{self.exp.name}[/]?",
                    "Cancel All",
                    require_yes=True
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
