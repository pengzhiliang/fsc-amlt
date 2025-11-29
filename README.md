# FSC - AMLT Job Manager 🚀

> **F**ast **S**tatus **C**hecker - A beautiful terminal-based AMLT job manager for Azure ML  
> No browser, no smart card, just pure terminal goodness!

[![PyPI version](https://badge.fury.io/py/fsc-amlt.svg)](https://badge.fury.io/py/fsc-amlt)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

<p align="center">
  <img src="https://raw.githubusercontent.com/pzzhang/fsc-amlt/main/docs/screenshot.png" alt="FSC Screenshot" width="800">
</p>

## ✨ Features

- 🖥️ **Beautiful TUI** - Full interactive terminal interface powered by Textual
- 📋 **Smart Grouping** - Experiments organized by status (Queued/Running/Passed/Failed/Killed)
- 🔔 **Real-time Notifications** - Get notified when job status changes
- 📊 **Detailed Views** - Drill down into individual jobs with log streaming
- ⚡ **Quick Actions** - One-key operations for cancel, refresh, copy, navigate
- 💾 **Smart Caching** - Terminal experiments cached locally for instant access
- 🔄 **Auto Status Correction** - Background task corrects experiment status automatically
- 📋 **Clipboard Support** - Copy experiment names with one keystroke
- 🎯 **Priority Focus** - Queued tab opens by default for monitoring job queue

## 🛠 Installation

### From PyPI (Recommended)

```bash
pip install fsc-amlt
```

### From Source

```bash
git clone https://github.com/pengzhiliang/fsc-amlt.git
cd fsc-amlt
pip install -e .
```

## 📋 Prerequisites

- Python 3.8+
- `amlt` CLI installed and configured ([AMLT Documentation](https://aka.ms/amulet))
- Terminal with Unicode support (most modern terminals)

## 🚀 Quick Start

Simply run:

```bash
fsc
```

The interactive TUI will launch immediately!

## 📸 Screenshots

### Main View - Experiments by Status
```
┌─────────────────────────────────────────────────────────────────────┐
│ ◌ Queued  ● Running  ✓ Passed  ✗ Failed  ⊘ Killed                  │
├─────────────────────────────────────────────────────────────────────┤
│ definite-chimp       ◌     turing-codex-cacentral  PRM      55m ago │
│ poetic-tadpole       ◌     turing-codex-cacentral  STD      5h ago  │
│ winning-joey         ●12   eastus2-prod            STD|HD   1d ago  │
└─────────────────────────────────────────────────────────────────────┘
```

### Job Details View
```
┌─────────────────────────────────────────────────────────────────────┐
│ winning-joey                                                        │
│ Cluster: eastus2-prod | Jobs: 16                                    │
├─────────────────────────────────────────────────────────────────────┤
│ :0  n2-sft              ● running   5d        https://...           │
│ :1  data_curation_1     ● running   5d        https://...           │
│ :2  data_curation_2     ✓ pass      4d 23h    https://...           │
└─────────────────────────────────────────────────────────────────────┘
```

## ⌨️ Keyboard Shortcuts

### Main Screen
| Key | Action |
|-----|--------|
| `↑` `↓` / `j` `k` | Navigate experiments |
| `Enter` | Open experiment details |
| `1`-`5` | Switch tabs (Queued/Running/Passed/Failed/Killed) |
| `r` | Refresh (+ auto status check on Queued/Running tabs) |
| `y` | Copy experiment name to clipboard |
| `Ctrl+K` | Cancel selected experiment |
| `n` | Clear notifications |
| `q` | Quit |

### Experiment Detail Screen
| Key | Action |
|-----|--------|
| `↑` `↓` / `j` `k` | Navigate jobs |
| `Enter` | View job logs |
| `r` | Refresh |
| `y` | Copy job name |
| `Ctrl+K` | Cancel selected job |
| `Ctrl+Shift+K` | Cancel ALL jobs |
| `Esc` / `q` | Go back |

### Log Screen
| Key | Action |
|-----|--------|
| `r` | Refresh from local cache |
| `d` | Download fresh logs from Azure |
| `Esc` / `q` | Go back |

## 🔧 CLI Commands

For scripting or quick operations:

```bash
# Launch TUI (default)
fsc

# List experiments
fsc list -n 30
fsc list -s running

# View experiment status
fsc status winning-joey

# View logs
fsc logs winning-joey -j :0

# Cancel experiment
fsc cancel winning-joey

# Clear cache
fsc cache --clear
```

## 🏗 Architecture

```
fsc/
├── __init__.py       # Package metadata
├── app.py            # TUI Application (Textual)
├── cli.py            # CLI commands (Click)
├── models.py         # Database models (Peewee/SQLite)
├── amlt_parser.py    # AMLT output parser
├── cache.py          # Caching layer
├── sync.py           # Background sync service
└── ui.py             # Rich UI components
```

## 🎯 Key Features Explained

### Smart Status Detection
For experiments with multiple jobs (hyperdrive), FSC uses job `:0` status to determine the overall experiment status. This prevents false "running" indicators when the main job has completed.

### Auto Status Correction
Every 5 minutes (or on manual refresh in Queued/Running tabs), FSC checks active experiments and corrects their status if they've actually completed.

### Local Caching
Terminal experiments (passed/failed/killed) are cached locally, so you can see historical experiments even if they've aged out of `amlt list`.

### Clipboard Integration
Press `y` to copy the selected experiment name - useful for running manual `amlt` commands.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 👥 Authors

- **Claude Opus 4.5** - AI pair programmer
- **Zhiliang Peng** - Human collaborator

## 🙏 Acknowledgments

- [Textual](https://github.com/Textualize/textual) - Amazing TUI framework
- [Rich](https://github.com/Textualize/rich) - Beautiful terminal formatting
- [AMLT](https://aka.ms/amulet) - Azure ML job management

---

*Built with ❤️ for ML researchers who just want to check their jobs without opening a browser.*
