"""
Terminal UI for the job manager.
Uses Rich library for beautiful terminal output.
"""

import os
import sys
from datetime import datetime
from typing import List, Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich.layout import Layout
from rich.style import Style
from rich import box

from .models import Experiment, Job, init_database, database


console = Console()


# Status colors
STATUS_COLORS = {
    'pass': 'green',
    'running': 'cyan',
    'queued': 'yellow',
    'prep': 'yellow',
    'fail': 'red',
    'failed': 'red',
    'cancelled': 'dim',
    'unknown': 'dim',
}

STATUS_ICONS = {
    'pass': '✓',
    'running': '●',
    'queued': '◌',
    'prep': '◎',
    'fail': '✗',
    'failed': '✗',
    'cancelled': '○',
    'unknown': '?',
}


def get_status_style(status: str) -> str:
    """Get the color style for a status."""
    return STATUS_COLORS.get(status.lower(), 'white')


def get_status_icon(status: str) -> str:
    """Get the icon for a status."""
    return STATUS_ICONS.get(status.lower(), '?')


def format_status(status: str, count: Optional[int] = None) -> Text:
    """Format status with color and icon."""
    icon = get_status_icon(status)
    color = get_status_style(status)
    
    if count is not None:
        text = f"{icon} {status.capitalize()} ({count})"
    else:
        text = f"{icon} {status.capitalize()}"
    
    return Text(text, style=color)


def create_experiments_table(
    experiments: List[Experiment],
    show_jobs: bool = False,
    compact: bool = False,
) -> Table:
    """Create a Rich table for experiments."""
    
    table = Table(
        title="📋 Experiments",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        row_styles=["", "dim"],
        expand=True,
    )
    
    # Columns
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Experiment", style="bold", min_width=15)
    table.add_column("Status", min_width=12)
    table.add_column("Jobs", justify="center", width=6)
    table.add_column("Cluster", style="cyan", min_width=10)
    table.add_column("Modified", style="yellow", width=10)
    table.add_column("Description", style="dim", overflow="ellipsis")
    
    if not compact:
        table.add_column("URL", style="blue", overflow="ellipsis", max_width=30)
    
    for idx, exp in enumerate(experiments, 1):
        # Build status cell with counts
        if exp.detail_fetched:
            status_parts = []
            if exp.pass_count > 0:
                status_parts.append(f"[green]✓{exp.pass_count}[/]")
            if exp.running_count > 0:
                status_parts.append(f"[cyan]●{exp.running_count}[/]")
            if exp.queued_count > 0:
                status_parts.append(f"[yellow]◌{exp.queued_count}[/]")
            if exp.fail_count > 0:
                status_parts.append(f"[red]✗{exp.fail_count}[/]")
            status_str = " ".join(status_parts) if status_parts else format_status(exp.status)
        else:
            status_str = format_status(exp.status, exp.job_count)
        
        row = [
            str(idx),
            exp.name,
            status_str,
            str(exp.job_count),
            exp.cluster or "-",
            exp.modified_at_str or "-",
            exp.description or "-",
        ]
        
        if not compact:
            row.append(exp.job_url or "-")
        
        table.add_row(*row)
    
    return table


def create_jobs_table(experiment: Experiment) -> Table:
    """Create a Rich table for jobs within an experiment."""
    
    jobs = Job.select().where(Job.experiment == experiment).order_by(Job.job_index)
    
    table = Table(
        title=f"🔧 Jobs in [bold]{experiment.name}[/]",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        expand=True,
    )
    
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Job Name", style="bold", min_width=20)
    table.add_column("Status", min_width=10)
    table.add_column("Duration", justify="right", width=10)
    table.add_column("Size", justify="right", width=10)
    table.add_column("Submitted", style="yellow", width=12)
    table.add_column("Flags", style="dim", width=10)
    
    for job in jobs:
        status_str = format_status(job.status)
        
        table.add_row(
            f":{job.job_index}",
            job.job_name,
            status_str,
            job.duration or "-",
            job.size or "-",
            job.submitted_at_str or "-",
            job.flags or "-",
        )
    
    return table


def create_summary_panel(experiments: List[Experiment]) -> Panel:
    """Create a summary panel with overall statistics."""
    
    total = len(experiments)
    running = sum(1 for e in experiments if e.status == 'running')
    queued = sum(1 for e in experiments if e.status in ('queued', 'prep'))
    passed = sum(1 for e in experiments if e.status == 'pass')
    failed = sum(1 for e in experiments if e.status in ('fail', 'failed'))
    
    # Total jobs
    total_jobs = sum(e.job_count for e in experiments)
    pass_jobs = sum(e.pass_count for e in experiments)
    run_jobs = sum(e.running_count for e in experiments)
    queue_jobs = sum(e.queued_count for e in experiments)
    fail_jobs = sum(e.fail_count for e in experiments)
    
    summary = Text()
    summary.append("📊 Summary\n\n", style="bold cyan")
    
    summary.append(f"Experiments: {total}\n", style="white")
    summary.append(f"  [green]✓ Pass: {passed}[/]  ")
    summary.append(f"[cyan]● Running: {running}[/]  ")
    summary.append(f"[yellow]◌ Queued: {queued}[/]  ")
    summary.append(f"[red]✗ Failed: {failed}[/]\n\n")
    
    summary.append(f"Total Jobs: {total_jobs}\n", style="white")
    summary.append(f"  [green]✓ {pass_jobs}[/]  ")
    summary.append(f"[cyan]● {run_jobs}[/]  ")
    summary.append(f"[yellow]◌ {queue_jobs}[/]  ")
    summary.append(f"[red]✗ {fail_jobs}[/]")
    
    return Panel(summary, border_style="cyan", box=box.ROUNDED)


def create_experiment_detail_panel(experiment: Experiment) -> Panel:
    """Create a detailed view panel for an experiment."""
    
    content = Text()
    content.append(f"📦 {experiment.name}\n\n", style="bold cyan")
    
    content.append("Status: ", style="bold")
    content.append(format_status(experiment.status))
    content.append("\n")
    
    content.append("Cluster: ", style="bold")
    content.append(f"{experiment.cluster or 'N/A'}\n", style="cyan")
    
    content.append("Workspace: ", style="bold")
    content.append(f"{experiment.workspace or 'N/A'}\n")
    
    content.append("Service: ", style="bold")
    content.append(f"{experiment.service or 'N/A'}\n")
    
    content.append("Flags: ", style="bold")
    content.append(f"{experiment.flags or 'N/A'}\n")
    
    content.append("\nDescription: ", style="bold")
    content.append(f"{experiment.description or 'No description'}\n", style="dim")
    
    if experiment.job_url:
        content.append("\nURL: ", style="bold")
        content.append(experiment.job_url, style="blue underline")
    
    # Job counts
    if experiment.detail_fetched:
        content.append("\n\nJob Status:\n", style="bold")
        content.append(f"  [green]✓ Pass: {experiment.pass_count}[/]\n")
        content.append(f"  [cyan]● Running: {experiment.running_count}[/]\n")
        content.append(f"  [yellow]◌ Queued: {experiment.queued_count}[/]\n")
        content.append(f"  [red]✗ Failed: {experiment.fail_count}[/]\n")
    
    return Panel(content, border_style="cyan", box=box.ROUNDED)


def print_experiments(
    experiments: List[Experiment],
    show_summary: bool = True,
    compact: bool = False,
):
    """Print experiments list."""
    if show_summary and experiments:
        console.print(create_summary_panel(experiments))
        console.print()
    
    console.print(create_experiments_table(experiments, compact=compact))


def print_experiment_detail(experiment: Experiment):
    """Print detailed view of an experiment."""
    console.print(create_experiment_detail_panel(experiment))
    console.print()
    console.print(create_jobs_table(experiment))


def print_status_bar(
    last_sync: Optional[datetime],
    is_syncing: bool = False,
    sync_interval: int = 60,
):
    """Print a status bar showing sync status."""
    text = Text()
    
    if is_syncing:
        text.append("🔄 Syncing...", style="yellow")
    else:
        text.append("✓ Synced", style="green")
    
    if last_sync:
        elapsed = (datetime.now() - last_sync).seconds
        text.append(f" ({elapsed}s ago)", style="dim")
    
    text.append(f"  |  Refresh: {sync_interval}s", style="dim")
    text.append("  |  [q]uit [r]efresh [/]filter [s]ync", style="dim")
    
    console.print(text)


def clear_screen():
    """Clear the terminal screen."""
    os.system('clear' if os.name == 'posix' else 'cls')


def print_header():
    """Print the application header."""
    header = Text()
    header.append("╔═══════════════════════════════════════════════════════════╗\n", style="cyan")
    header.append("║  ", style="cyan")
    header.append("FSC", style="bold magenta")
    header.append(" - ", style="cyan")
    header.append("F", style="red")
    header.append("uck ", style="white")
    header.append("S", style="red")
    header.append("mart ", style="white")
    header.append("C", style="red")
    header.append("ard", style="white")
    header.append("  |  AMLT Job Manager", style="cyan")
    header.append("               ║\n", style="cyan")
    header.append("╚═══════════════════════════════════════════════════════════╝", style="cyan")
    console.print(header)
    console.print()
