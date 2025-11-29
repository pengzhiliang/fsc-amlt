"""
Custom widgets for FSC TUI application.
"""

from __future__ import annotations

from typing import List

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static, ListItem, Input
from textual.binding import Binding

from ..data import ExpData, JobData, StatusChange
from ..utils import STATUS_DISPLAY


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
    
    def __init__(self, message: str, action_name: str = "Confirm", require_yes: bool = False):
        """
        Initialize confirmation dialog.
        
        Args:
            message: The warning message to display
            action_name: Name of the action (e.g., "Cancel", "Delete")
            require_yes: If True, user must type 'yes' to confirm
        """
        super().__init__()
        self.message = message
        self.action_name = action_name
        self.require_yes = require_yes
    
    def compose(self) -> ComposeResult:
        with Container(id="dialog-container"):
            yield Static(f"[bold red]⚠️  WARNING ⚠️[/]\n\n{self.message}", id="dialog-message")
            if self.require_yes:
                yield Static(f"\n[bold yellow]Type '[white]yes[/]' to confirm:[/]", id="dialog-hint")
                yield Input(placeholder="Type: yes", id="confirm-input")
            else:
                yield Static(f"\n[bold]Press [green]Y[/] to {self.action_name}, [red]N/Esc[/] to cancel[/]", id="dialog-hint")
    
    def on_mount(self):
        if self.require_yes:
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
        """Handle Y/N keys only if not requiring 'yes' input."""
        if not self.require_yes:
            if event.key == "y":
                self.dismiss(True)
            elif event.key == "n":
                self.dismiss(False)
    
    def action_cancel(self):
        self.dismiss(False)
