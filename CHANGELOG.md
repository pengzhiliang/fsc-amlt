# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2024-11-28

### Added
- 🎯 **Priority Queue Focus**: Queued tab now opens by default for monitoring job queue
- 🔄 **Auto Status Correction**: Background task (every 5 minutes) checks and corrects status of active experiments
- 📋 **Clipboard Support**: Press `y` to copy experiment/job name to clipboard
- 🏷️ **FLAGS Column**: Display job flags (PRM/STD/HD) in main list for quick identification
- ⚡ **Manual Status Check**: Press `r` in Queued/Running tabs to trigger immediate status verification
- 📊 **Progress Indicators**: Show progress when checking experiment statuses
- 🔍 **Latest Retry Logs**: Automatically find and display logs from latest retry attempt
- ✅ **Simplified Confirmation**: Cancel operations now only require typing "yes"

### Changed
- 🖱️ **Navigation**: Changed from single-click to Enter key for opening experiment details
- 📐 **Column Alignment**: Fixed alignment issues with Rich markup in status display
- 🔧 **Status Detection**: Use job :0 status for multi-job experiments to determine overall status

### Fixed
- 🐛 Fixed log path issues with colon prefix in job names
- 🐛 Fixed Rich markup tag mismatch causing crash on cancel dialog
- 🐛 Fixed column misalignment due to markup tags in width calculation

## [0.1.0] - 2024-11-27

### Added
- 🖥️ Initial TUI application with Textual framework
- 📋 Experiments grouped by status (Running/Queued/Passed/Failed/Killed)
- 🔔 Real-time status change notifications
- 📊 Detailed job views with log display
- ⚡ Keyboard shortcuts for all operations
- 💾 Local caching for terminal experiments
- 🔧 CLI commands for scripting

---

## Legend

- 🎯 Feature
- 🔄 Enhancement
- 🐛 Bug fix
- 📋 Documentation
- ⚡ Performance
