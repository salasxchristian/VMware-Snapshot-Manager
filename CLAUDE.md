# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

VMware Snapshot Manager is a PyQt6-based GUI application for managing VMware snapshots across multiple vCenter servers. It's specifically designed for system administrators managing patching snapshots.

## Development Commands

### Installation
```bash
pip install -r requirements.txt
```

### Running the Application
```bash
python vmware_snapshot_manager.py
```

### Dependencies
The application requires:
- Python 3.6+
- PyQt6 (GUI framework)
- pyVmomi (VMware SDK)
- keyring (secure credential storage)
- urllib3 (HTTP library)

## Architecture

### Core Components

**Main Application Class**: `SnapshotManagerWindow` (lines 268-1605)
- Main window managing UI, connections, and operations
- Handles window positioning, progress tracking, and user interactions

**Worker Threads**: Background processing to prevent UI blocking
- `SnapshotFetchWorker` (lines 24-96): Fetches snapshots from vCenters
- `SnapshotDeleteWorker` (lines 202-266): Handles bulk snapshot deletion  
- `SnapshotCreateWorker` (lines 1406-1567): Creates snapshots across multiple VMs

**Dialog Classes**: 
- `AddVCenterDialog` (lines 98-201): vCenter connection setup
- `CreateSnapshotsDialog` (lines 1288-1381): Bulk snapshot creation
- `AutoConnectDialog` (lines 1569-1604): Auto-connect preferences

**Configuration Management**: `ConfigManager` (lines 1236-1286)
- Handles server configurations and secure password storage via system keychain
- Uses JSON files for server lists and system keyring for passwords

### Key Design Patterns

**Threading Model**: All VMware operations run in worker threads with progress signals to prevent UI freezing

**Progress Standardization**: Unified progress system via `update_progress()` method (lines 1116-1137) - all workers emit (value, total, message) signals

**Caching Strategy**: Newly created snapshots are added directly to the tree without refetching (see `handle_created_snapshot` at line 1078)

**Connection Resilience**: Auto-reconnection timer checks connections every 5 minutes and attempts reconnection using stored credentials

### Security Features

- Passwords stored in system keychain (macOS Keychain, Windows Credential Manager, Linux Secret Service)
- SSL certificate verification disabled for VMware connections (common in enterprise environments)
- No hardcoded credentials

### UI Patterns

**Tree Widget**: Main snapshot display with checkboxes, sorting, context menus, and color coding:
- Gray background: Chain snapshots (cannot be deleted)
- Yellow background: Snapshots older than 3 business days

**Progress Indication**: Consistent progress bars across all operations with percentage and descriptive messages

**Window Management**: All dialogs save/restore their positions using QSettings

## Important Implementation Notes

- All VMware API calls use SSL context with disabled certificate verification
- Business day calculation excludes weekends for snapshot age warnings
- Snapshot chains are detected and prevented from deletion for safety
- Auto-connect feature available for saved vCenter connections
- Copy functionality on double-click and context menus for easy data extraction

## Testing

No automated test framework is currently implemented. Manual testing should focus on:
- vCenter connectivity across different environments
- Snapshot operations (create/delete) with proper error handling
- UI responsiveness during long operations
- Window positioning and settings persistence