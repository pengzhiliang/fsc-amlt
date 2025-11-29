"""
Main screen showing experiments grouped by status.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Dict

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Header, Footer, Static, ListView, TabbedContent, TabPane

from .base import TabbedListScreen
from .detail_screen import ExperimentDetailScreen
from ..data import ExpData, StatusChange
from ..cache import get_cache, get_tag_cache, TERMINAL_STATES
from ..utils import STATUS_DISPLAY, parse_time_ago
from ..widgets import ExperimentListItem, NotificationBar, ConfirmDialog, TagInputDialog
from ..amlt_parser import get_experiments, get_experiment_status, AmltParser, ExperimentInfo

# Try to import pyperclip for clipboard support
try:
    import pyperclip
    HAS_CLIPBOARD = True
except ImportError:
    HAS_CLIPBOARD = False


class MainScreen(TabbedListScreen):
    """Main screen showing experiments grouped by status."""
    
    TABS_ID = "tabs"
    TAB_MAPPING = {
        "tab-running": ("list-running", 'running'),
        "tab-queued": ("list-queued", 'queued'),
        "tab-passed": ("list-passed", 'pass'),
        "tab-failed": ("list-failed", 'fail'),
        "tab-killed": ("list-killed", 'killed'),
    }
    
    BINDINGS = [
        Binding("enter", "select_experiment", "Open", priority=True),
        Binding("r", "refresh", "Refresh"),
        Binding("y", "copy_name", "Copy"),
        Binding("t", "set_tag", "Tag"),
        Binding("ctrl+k", "cancel_experiment", "Cancel"),
        Binding("n", "clear_notifications", "Clear"),
        Binding("q", "quit", "Quit"),
        *TabbedListScreen.COMMON_BINDINGS,
    ]
    
    def __init__(self):
        super().__init__()
        self.all_experiments: List[ExpData] = []
        self.grouped: Dict[str, List[ExpData]] = {}
        self.last_statuses: Dict[str, str] = {}
        self.tag_cache = get_tag_cache()
        self._tab_order = ["tab-queued", "tab-running", "tab-passed", "tab-failed", "tab-killed"]
    
    def _get_data_for_status(self, status: str) -> List[ExpData]:
        return self.grouped.get(status, [])
    
    def compose(self) -> ComposeResult:
        yield Header()
        
        with Container(id="main-container"):
            yield NotificationBar(id="notifications")
            yield Static(id="summary-bar")
            yield Static("", id="main-loading-text")
            
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
        
        yield Footer()
    
    def on_mount(self):
        self.query_one("#notifications", NotificationBar).display = False
        self.cache = get_cache()
        self._fetch_experiments()
        self.set_interval(300, self._fetch_experiments)
        self.set_interval(300, self._correct_active_statuses)
    
    def _show_loading(self):
        """Show loading indicator."""
        self.query_one("#main-loading-text", Static).update("[yellow]⟳ Refreshing...[/]")
    
    def _hide_loading(self):
        """Hide loading indicator."""
        self.query_one("#main-loading-text", Static).update("")
    
    @work(thread=True)
    def _fetch_experiments(self):
        """Fetch experiments in background thread."""
        self.app.call_from_thread(self._show_loading)
        
        exp_infos = get_experiments(n_recent=50)
        cached_exps = self.cache.get_all()
        
        self.app.call_from_thread(self._update_display, exp_infos, cached_exps)

    @work(thread=True, exclusive=True, name="correct_status")
    def _correct_active_statuses(self):
        """
        Background task to correct status of active experiments.
        Fetches detailed status for running/queued experiments and updates cache.
        """
        active_exps = []
        for status in ('running', 'queued'):
            if status in self.grouped:
                active_exps.extend(self.grouped[status])
        
        if not active_exps:
            return
        
        active_exps = active_exps[:10]
        corrections = []
        
        for exp in active_exps:
            detail = get_experiment_status(exp.name)
            if not detail or not detail.jobs:
                continue
            
            if len(detail.jobs) > 1:
                job0 = next((j for j in detail.jobs if j.index == 0), None)
                if job0:
                    job0_status = job0.status.lower().split()[0] if job0.status else ''
                    if job0_status in ('pass', 'fail', 'failed', 'killed'):
                        new_status = job0_status if job0_status != 'failed' else 'fail'
                        if exp.status != new_status:
                            corrections.append((exp.name, exp.status, new_status, detail))
            else:
                job_status = detail.jobs[0].status.lower().split()[0] if detail.jobs[0].status else ''
                if job_status in ('pass', 'fail', 'failed', 'killed'):
                    new_status = job_status if job_status != 'failed' else 'fail'
                    if exp.status != new_status:
                        corrections.append((exp.name, exp.status, new_status, detail))
        
        if corrections:
            self.app.call_from_thread(self._apply_status_corrections, corrections)
    
    def _apply_status_corrections(self, corrections):
        """Apply status corrections and update display."""
        notifications = self.query_one("#notifications", NotificationBar)
        
        for exp_name, old_status, new_status, detail in corrections:
            self.cache.force_add(
                name=exp_name,
                status=new_status,
                cluster=detail.cluster,
                job_count=detail.n_jobs,
                pass_count=detail.pass_count,
                fail_count=detail.fail_count,
                killed_count=len([j for j in detail.jobs if j.status.lower().split()[0] == 'killed']),
            )
            
            notifications.add_notification(StatusChange(
                exp_name=exp_name,
                old_status=old_status,
                new_status=new_status
            ))
            notifications.display = True
        
        self._fetch_experiments()

    def _update_display(self, exp_infos: List[ExperimentInfo], cached_exps=None):
        """Update experiments display."""
        self._hide_loading()
        
        notifications = self.query_one("#notifications", NotificationBar)
        api_exp_names = set()
        
        self.all_experiments = []
        for info in exp_infos:
            exp = ExpData.from_info(info)
            # Load tag from cache
            exp.tag = self.tag_cache.get(exp.name)
            self.all_experiments.append(exp)
            api_exp_names.add(exp.name)
            
            if exp.is_terminal():
                self.cache.add_from_exp_data(exp)
            
            old_status = self.last_statuses.get(exp.name)
            if old_status and old_status != exp.status:
                notifications.add_notification(StatusChange(
                    exp_name=exp.name,
                    old_status=old_status,
                    new_status=exp.status
                ))
            self.last_statuses[exp.name] = exp.status
        
        if cached_exps:
            for cached in cached_exps:
                if cached.name not in api_exp_names:
                    exp = ExpData.from_cached(cached)
                    # Load tag from cache
                    exp.tag = self.tag_cache.get(exp.name)
                    self.all_experiments.append(exp)
        
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
        
        for status in self.grouped:
            self.grouped[status].sort(key=lambda e: parse_time_ago(e.modified))
        
        cached_count = sum(1 for e in self.all_experiments if e.from_cache)
        
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
    
    def action_refresh(self):
        self._show_loading()
        self._fetch_experiments()
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
        """Cancel selected experiment - requires typing 'yes' to confirm."""
        list_view, experiments = self._get_current_list()
        if list_view.index is not None and list_view.index < len(experiments):
            exp = experiments[list_view.index]
            if exp.status in ('running', 'queued', 'prep'):
                self.app.push_screen(
                    ConfirmDialog(
                        f"[bold red]DANGER:[/] Cancel experiment [bold cyan]{exp.name}[/]?\n\nThis will kill ALL jobs in this experiment!",
                        "Cancel",
                        require_yes=True
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
                self.notify(f"📋 {exp.name} (install pyperclip for clipboard)", timeout=5)
    
    def action_clear_notifications(self):
        self.query_one("#notifications", NotificationBar).clear()
    
    def action_set_tag(self):
        """Set a tag for the selected experiment."""
        list_view, experiments = self._get_current_list()
        if list_view.index is not None and list_view.index < len(experiments):
            exp = experiments[list_view.index]
            current_tag = self.tag_cache.get(exp.name)
            self.app.push_screen(
                TagInputDialog(exp.name, current_tag),
                callback=lambda tag: self._apply_tag(exp, tag) if tag is not None else None
            )
    
    def _apply_tag(self, exp: ExpData, tag: str):
        """Apply tag to experiment and refresh display."""
        self.tag_cache.set(exp.name, tag)
        exp.tag = tag
        # Refresh the current list to show updated tag
        self._refresh_current_list()
        if tag:
            self.notify(f"🏷️ Tagged '{exp.name}' as #{tag}", timeout=2)
        else:
            self.notify(f"🏷️ Removed tag from '{exp.name}'", timeout=2)
    
    def _refresh_current_list(self):
        """Refresh the current list view to reflect changes."""
        for status, list_id in [
            ('running', 'list-running'),
            ('queued', 'list-queued'),
            ('pass', 'list-passed'),
            ('fail', 'list-failed'),
            ('killed', 'list-killed'),
        ]:
            list_view = self.query_one(f"#{list_id}", ListView)
            list_view.clear()
            for exp in self.grouped.get(status, []):
                list_view.append(ExperimentListItem(exp))
