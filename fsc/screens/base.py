"""
Base screen with common tab and cursor navigation logic.
"""

from __future__ import annotations

from typing import List, Dict, Tuple, Any

from textual.screen import Screen
from textual.widgets import ListView, TabbedContent
from textual.binding import Binding


class TabbedListScreen(Screen):
    """
    Base screen that provides common functionality for screens with
    tabbed content and list views.
    """
    
    # Subclasses should define these
    TABS_ID: str = "tabs"  # ID of the TabbedContent widget
    TAB_MAPPING: Dict[str, Tuple[str, str]] = {}  # tab_id -> (list_id, status_key)
    
    # Common bindings for tab navigation
    COMMON_BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up", show=False),
        Binding("1", "tab_1", "Tab 1", show=False),
        Binding("2", "tab_2", "Tab 2", show=False),
        Binding("3", "tab_3", "Tab 3", show=False),
        Binding("4", "tab_4", "Tab 4", show=False),
        Binding("5", "tab_5", "Tab 5", show=False),
    ]
    
    def __init__(self):
        super().__init__()
        self._tab_order: List[str] = []  # Will be set by subclass
    
    def _get_current_list(self) -> Tuple[ListView, List[Any]]:
        """
        Get the currently active list and its data.
        Subclasses should override to return the correct data list.
        """
        tabs = self.query_one(f"#{self.TABS_ID}", TabbedContent)
        active = tabs.active
        
        if active in self.TAB_MAPPING:
            list_id, status = self.TAB_MAPPING[active]
            return self.query_one(f"#{list_id}", ListView), self._get_data_for_status(status)
        
        # Fallback to first tab
        if self.TAB_MAPPING:
            first_tab = list(self.TAB_MAPPING.keys())[0]
            list_id, status = self.TAB_MAPPING[first_tab]
            return self.query_one(f"#{list_id}", ListView), self._get_data_for_status(status)
        
        raise ValueError("No TAB_MAPPING defined")
    
    def _get_data_for_status(self, status: str) -> List[Any]:
        """
        Get data for a given status. Subclasses must override.
        """
        raise NotImplementedError
    
    def _switch_to_tab(self, index: int):
        """Switch to tab by index (0-based)."""
        if 0 <= index < len(self._tab_order):
            self.query_one(f"#{self.TABS_ID}", TabbedContent).active = self._tab_order[index]
    
    # Cursor actions
    def action_cursor_down(self):
        list_view, _ = self._get_current_list()
        list_view.action_cursor_down()
    
    def action_cursor_up(self):
        list_view, _ = self._get_current_list()
        list_view.action_cursor_up()
    
    # Tab actions (1-5 keys)
    def action_tab_1(self):
        self._switch_to_tab(0)
    
    def action_tab_2(self):
        self._switch_to_tab(1)
    
    def action_tab_3(self):
        self._switch_to_tab(2)
    
    def action_tab_4(self):
        self._switch_to_tab(3)
    
    def action_tab_5(self):
        self._switch_to_tab(4)
