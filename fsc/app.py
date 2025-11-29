"""
FSC - Interactive TUI Application
A modern terminal-based AMLT job manager.
"""

from __future__ import annotations

from textual.app import App
from textual.binding import Binding

from .screens import MainScreen


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
    
    #main-loading-text {
        height: 1;
        text-align: center;
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
    
    #detail-container {
        height: 100%;
    }
    
    #job-tabs {
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
            "↑↓/jk=Navigate | Enter=Open | r=Refresh | Ctrl+k=Cancel | 1-5=Tabs | q=Quit",
            timeout=5
        )


def run_app():
    """Run the FSC application."""
    app = FSCApp()
    app.run()


if __name__ == "__main__":
    run_app()
