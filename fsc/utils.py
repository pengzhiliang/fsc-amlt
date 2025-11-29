"""
FSC - Utility functions and shared constants.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict


# Status styling - icons, colors, and display names
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


def format_time_ago(timestamp: float) -> str:
    """Format timestamp as relative time (e.g., '5m ago', '2h ago')."""
    now = datetime.now().timestamp()
    diff = now - timestamp
    
    if diff < 60:
        return f"{int(diff)}s ago"
    elif diff < 3600:
        return f"{int(diff / 60)}m ago"
    elif diff < 86400:
        return f"{int(diff / 3600)}h ago"
    else:
        return f"{int(diff / 86400)}d ago"


def get_amlt_output_dir() -> str:
    """Get AMLT default output directory from cache."""
    from .cache import get_config_cache
    return get_config_cache().get_output_dir()


def normalize_status(status: str) -> str:
    """Normalize status string to standard form."""
    status = status.lower().split()[0] if status else ''
    if status == 'failed':
        return 'fail'
    if status == 'prep':
        return 'queued'
    return status
