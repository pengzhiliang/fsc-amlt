"""
Main CLI entry point for FSC - AMLT Job Manager.
"""

import os
import sys
import time
import signal
import threading
from datetime import datetime
from typing import Optional

import click
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.live import Live
from rich.table import Table

from . import __version__
from .models import Experiment, Job, SyncLog, init_database, close_database, database
from .sync import SyncService, start_sync_service, stop_sync_service, get_sync_service
from .ui import (
    console, print_header, print_experiments, print_experiment_detail,
    print_status_bar, clear_screen, create_experiments_table,
    create_summary_panel, STATUS_COLORS
)
from .amlt_parser import get_experiments, get_experiment_status


# Global state
_should_exit = False


def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully."""
    global _should_exit
    _should_exit = True
    console.print("\n[yellow]Shutting down...[/]")


@click.group(invoke_without_command=True)
@click.option('--version', '-V', is_flag=True, help='Show version')
@click.pass_context
def main(ctx, version):
    """
    FSC - Fuck Smart Card
    
    Terminal-based AMLT Job Manager for Azure ML.
    Because who needs a smart card anyway? 🖕
    
    Run 'fsc' without arguments to launch the interactive TUI app.
    """
    if version:
        console.print(f"[cyan]FSC[/] version [bold]{__version__}[/]")
        return
    
    if ctx.invoked_subcommand is None:
        # Default: launch TUI app
        from .app import run_app
        run_app()


@main.command('app', help='Launch interactive TUI app')
def launch_app():
    """Launch the interactive TUI application."""
    from .app import run_app
    run_app()


@main.command('list', help='List experiments (CLI mode)')
@click.option('--limit', '-n', default=30, help='Number of experiments to show')
@click.option('--status', '-s', type=click.Choice(['all', 'running', 'queued', 'pass', 'fail']), 
              default='all', help='Filter by status')
@click.option('--compact', '-c', is_flag=True, help='Compact view')
@click.option('--no-sync', is_flag=True, help='Skip syncing, show cached data only')
@click.option('--refresh', '-r', is_flag=True, help='Force refresh from AMLT')
def list_experiments(limit, status, compact, no_sync, refresh):
    """List all experiments."""
    init_database()
    
    # Sync if needed
    if not no_sync or refresh:
        with console.status("[cyan]Syncing experiments...[/]"):
            sync = SyncService()
            sync.sync_list(n_recent=limit)
    
    # Query database
    query = Experiment.select().order_by(Experiment.updated_at.desc())
    
    if status != 'all':
        if status == 'queued':
            query = query.where(Experiment.status.in_(['queued', 'prep']))
        else:
            query = query.where(Experiment.status == status)
    
    experiments = list(query.limit(limit))
    
    if not experiments:
        console.print("[yellow]No experiments found.[/]")
        console.print("Try running [cyan]fsc sync[/] first.")
        return
    
    print_header()
    print_experiments(experiments, show_summary=True, compact=compact)
    
    close_database()


@main.command('status', help='Show detailed status of an experiment')
@click.argument('experiment_name')
@click.option('--refresh', '-r', is_flag=True, help='Force refresh from AMLT')
def show_status(experiment_name, refresh):
    """Show detailed status of an experiment."""
    init_database()
    
    # Try to find experiment
    try:
        exp = Experiment.get(Experiment.name == experiment_name)
    except Experiment.DoesNotExist:
        exp = None
    
    # Sync status
    if refresh or not exp or not exp.detail_fetched:
        with console.status(f"[cyan]Fetching status for {experiment_name}...[/]"):
            sync = SyncService()
            sync.sync_experiment_status(experiment_name)
        
        try:
            exp = Experiment.get(Experiment.name == experiment_name)
        except Experiment.DoesNotExist:
            console.print(f"[red]Experiment '{experiment_name}' not found.[/]")
            return
    
    print_header()
    print_experiment_detail(exp)
    
    close_database()


@main.command('sync', help='Sync all experiments from AMLT')
@click.option('--full', '-f', is_flag=True, help='Full sync including all job details')
@click.option('--limit', '-n', default=50, help='Number of experiments to sync')
def sync_experiments(full, limit):
    """Manually sync experiments from AMLT."""
    init_database()
    
    sync = SyncService()
    
    with console.status("[cyan]Syncing experiment list...[/]"):
        success = sync.sync_list(n_recent=limit)
    
    if not success:
        console.print("[red]Failed to sync experiments.[/]")
        return
    
    experiments = Experiment.select().order_by(Experiment.updated_at.desc()).limit(limit)
    console.print(f"[green]✓ Synced {experiments.count()} experiments[/]")
    
    if full:
        # Sync details for active experiments
        active_exps = [e for e in experiments if e.status in ('running', 'queued', 'prep')]
        
        with console.status(f"[cyan]Syncing {len(active_exps)} active experiments...[/]"):
            for exp in active_exps:
                sync.sync_experiment_status(exp.name)
                console.print(f"  [dim]Synced {exp.name}[/]")
        
        console.print(f"[green]✓ Detailed sync completed[/]")
    
    close_database()


@main.command('watch', help='Watch experiments in real-time')
@click.option('--interval', '-i', default=30, help='Refresh interval in seconds')
@click.option('--limit', '-n', default=20, help='Number of experiments to show')
@click.option('--status', '-s', type=click.Choice(['all', 'running', 'queued', 'pass', 'fail']),
              default='all', help='Filter by status')
def watch_experiments(interval, limit, status):
    """Watch experiments with auto-refresh."""
    global _should_exit
    
    signal.signal(signal.SIGINT, signal_handler)
    init_database()
    
    sync = SyncService()
    last_sync = None
    
    console.print("[cyan]Starting watch mode. Press Ctrl+C to exit.[/]")
    console.print(f"[dim]Refresh interval: {interval}s[/]\n")
    
    try:
        while not _should_exit:
            # Sync
            sync.sync_list(n_recent=limit)
            last_sync = datetime.now()
            
            # Query
            query = Experiment.select().order_by(Experiment.updated_at.desc())
            if status != 'all':
                if status == 'queued':
                    query = query.where(Experiment.status.in_(['queued', 'prep']))
                else:
                    query = query.where(Experiment.status == status)
            
            experiments = list(query.limit(limit))
            
            # Display
            clear_screen()
            print_header()
            print_experiments(experiments, show_summary=True, compact=True)
            console.print()
            print_status_bar(last_sync, sync_interval=interval)
            
            # Wait
            for _ in range(interval):
                if _should_exit:
                    break
                time.sleep(1)
    
    except KeyboardInterrupt:
        pass
    finally:
        close_database()
        console.print("\n[cyan]Watch mode ended.[/]")


@main.command('logs', help='View logs of a job')
@click.argument('experiment_name')
@click.option('--job', '-j', default=':0', help='Job name or index (e.g., :0, :1)')
@click.option('--follow', '-f', is_flag=True, help='Follow log output')
@click.option('--lines', '-n', default=50, help='Number of lines to show')
def view_logs(experiment_name, job, follow, lines):
    """View logs of a specific job."""
    import subprocess
    
    cmd = ['amlt', 'logs']
    
    if follow:
        cmd.append('-f')
    else:
        cmd.extend(['-n', str(lines)])
    
    cmd.extend([experiment_name, job])
    
    console.print(f"[dim]Running: {' '.join(cmd)}[/]\n")
    
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        pass


@main.command('cancel', help='Cancel an experiment or job')
@click.argument('experiment_name')
@click.option('--job', '-j', default=None, help='Specific job to cancel')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation (DANGEROUS)')
def cancel_experiment(experiment_name, job, yes):
    """Cancel an experiment or specific job. Requires typing the name to confirm."""
    import subprocess
    
    if not yes:
        console.print(f"\n[bold red]⚠️  WARNING ⚠️[/]")
        if job:
            console.print(f"You are about to cancel job [bold cyan]{job}[/] in experiment [bold]{experiment_name}[/]")
            confirm_text = job.lstrip(':')
        else:
            console.print(f"You are about to cancel [bold red]ALL JOBS[/] in experiment [bold cyan]{experiment_name}[/]")
            confirm_text = experiment_name
        
        console.print(f"\n[yellow]Type '[bold white]{confirm_text}[/yellow]' to confirm:[/]")
        user_input = Prompt.ask("Confirm")
        
        if user_input.strip() != confirm_text:
            console.print("[red]Confirmation mismatch. Operation cancelled.[/]")
            return
    
    cmd = ['amlt', 'cancel', '-y', experiment_name]
    if job:
        cmd.append(job)
    
    console.print(f"[dim]Running: {' '.join(cmd)}[/]\n")
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        console.print(f"[green]✓ Cancelled successfully[/]")
    else:
        console.print(f"[red]Failed to cancel: {result.stderr}[/]")


@main.command('ssh', help='SSH into a running job')
@click.argument('experiment_name')
@click.option('--job', '-j', default=':0', help='Job name or index')
def ssh_to_job(experiment_name, job):
    """SSH into a running job."""
    import subprocess
    
    cmd = ['amlt', 'ssh', experiment_name, job]
    console.print(f"[dim]Running: {' '.join(cmd)}[/]\n")
    
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        pass


@main.command('open', help='Open experiment URL (prints URL for terminal copy)')
@click.argument('experiment_name')
def open_experiment(experiment_name):
    """Show the experiment URL for copying."""
    init_database()
    
    try:
        exp = Experiment.get(Experiment.name == experiment_name)
        if exp.job_url:
            console.print(f"\n[cyan]Experiment:[/] {exp.name}")
            console.print(f"[cyan]URL:[/] [blue underline]{exp.job_url}[/]\n")
            console.print("[dim]Copy the URL above and paste in your browser.[/]")
        else:
            console.print(f"[yellow]No URL found for '{experiment_name}'[/]")
    except Experiment.DoesNotExist:
        console.print(f"[red]Experiment '{experiment_name}' not found in cache.[/]")
        console.print("Try running [cyan]fsc sync[/] first.")
    
    close_database()


@main.command('stats', help='Show statistics')
def show_stats():
    """Show job statistics."""
    init_database()
    
    total = Experiment.select().count()
    
    if total == 0:
        console.print("[yellow]No data. Run [cyan]fsc sync[/] first.[/]")
        return
    
    stats = {
        'pass': Experiment.select().where(Experiment.status == 'pass').count(),
        'running': Experiment.select().where(Experiment.status == 'running').count(),
        'queued': Experiment.select().where(Experiment.status.in_(['queued', 'prep'])).count(),
        'fail': Experiment.select().where(Experiment.status.in_(['fail', 'failed'])).count(),
    }
    
    # Jobs
    total_jobs = sum(e.job_count for e in Experiment.select())
    
    print_header()
    
    from rich import box as rich_box
    table = Table(title="📊 Job Statistics", box=rich_box.ROUNDED)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    
    table.add_row("Total Experiments", str(total))
    table.add_row("Total Jobs", str(total_jobs))
    table.add_row("")
    table.add_row("[green]✓ Passed[/]", str(stats['pass']))
    table.add_row("[cyan]● Running[/]", str(stats['running']))
    table.add_row("[yellow]◌ Queued[/]", str(stats['queued']))
    table.add_row("[red]✗ Failed[/]", str(stats['fail']))
    
    console.print(table)
    
    # Recent syncs
    recent_syncs = SyncLog.select().order_by(SyncLog.created_at.desc()).limit(5)
    
    if recent_syncs.count() > 0:
        console.print()
        sync_table = Table(title="🔄 Recent Syncs", box=rich_box.ROUNDED)
        sync_table.add_column("Time", style="dim")
        sync_table.add_column("Type")
        sync_table.add_column("Status")
        sync_table.add_column("Message", style="dim")
        
        for log in recent_syncs:
            status = "[green]✓[/]" if log.success else "[red]✗[/]"
            sync_table.add_row(
                log.created_at.strftime("%H:%M:%S"),
                log.sync_type,
                status,
                log.message or "-"
            )
        
        console.print(sync_table)
    
    close_database()


@main.command('clear', help='Clear local cache')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation')
def clear_cache(yes):
    """Clear the local database cache."""
    from pathlib import Path
    from .models import DEFAULT_DB_PATH
    
    if not yes:
        if not Confirm.ask("Clear all cached data?"):
            return
    
    if DEFAULT_DB_PATH.exists():
        DEFAULT_DB_PATH.unlink()
        console.print("[green]✓ Cache cleared[/]")
    else:
        console.print("[yellow]No cache to clear[/]")


@main.command('cache', help='Manage experiment cache')
@click.option('--stats', '-s', is_flag=True, help='Show cache statistics')
@click.option('--list', '-l', 'list_cache', is_flag=True, help='List cached experiments')
@click.option('--clear', '-c', is_flag=True, help='Clear the cache')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation for clear')
def manage_cache(stats, list_cache, clear, yes):
    """Manage the experiment cache for terminal states."""
    from rich import box as rich_box
    from .cache import get_cache, TERMINAL_STATES
    
    cache = get_cache()
    
    if clear:
        if not yes:
            if not Confirm.ask("Clear experiment cache?"):
                return
        cache.clear()
        console.print("[green]✓ Experiment cache cleared[/]")
        return
    
    if list_cache:
        cached_exps = cache.get_all()
        if not cached_exps:
            console.print("[yellow]No cached experiments.[/]")
            return
        
        table = Table(title="💾 Cached Experiments", box=rich_box.ROUNDED)
        table.add_column("Name", style="cyan")
        table.add_column("Status")
        table.add_column("Jobs", justify="right")
        table.add_column("Cached At", style="dim")
        
        for exp in sorted(cached_exps, key=lambda x: x.cached_at, reverse=True):
            status_color = STATUS_COLORS.get(exp.status, 'white')
            table.add_row(
                exp.name[:50] + ('...' if len(exp.name) > 50 else ''),
                f"[{status_color}]{exp.status}[/]",
                str(exp.job_count),
                exp.cached_at[:19] if exp.cached_at else '-'
            )
        
        console.print(table)
        return
    
    # Default: show stats
    cache_stats = cache.stats()
    
    table = Table(title="💾 Experiment Cache Statistics", box=rich_box.ROUNDED)
    table.add_column("Status", style="cyan")
    table.add_column("Count", justify="right")
    
    table.add_row("[bold]Total Cached[/]", f"[bold]{cache_stats['total']}[/]")
    table.add_row("")
    table.add_row("[green]✓ Passed[/]", str(cache_stats.get('pass', 0)))
    table.add_row("[red]✗ Failed[/]", str(cache_stats.get('fail', 0) + cache_stats.get('failed', 0)))
    table.add_row("[magenta]⊘ Killed[/]", str(cache_stats.get('killed', 0)))
    table.add_row("[dim]Cancelled[/]", str(cache_stats.get('cancelled', 0)))
    
    console.print(table)
    console.print(f"\n[dim]Cache location: {cache.cache_file}[/]")


@main.command('daemon', help='Run background sync daemon')
@click.option('--interval', '-i', default=60, help='Sync interval in seconds')
def run_daemon(interval):
    """Run as a background sync daemon."""
    global _should_exit
    
    signal.signal(signal.SIGINT, signal_handler)
    init_database()
    
    console.print(f"[cyan]Starting sync daemon (interval: {interval}s)[/]")
    console.print("[dim]Press Ctrl+C to stop[/]\n")
    
    sync = start_sync_service(sync_interval=interval)
    
    try:
        while not _should_exit:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        stop_sync_service()
        close_database()
        console.print("\n[cyan]Daemon stopped.[/]")


if __name__ == '__main__':
    main()
