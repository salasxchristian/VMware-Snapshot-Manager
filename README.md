# VMware Snapshot Manager

A Python-based GUI application for managing VMware snapshots across multiple vCenter servers. This tool is specifically designed to help system administrators manage patching snapshots efficiently.

## Features

- Connect to multiple vCenter servers simultaneously
- Secure credential storage using system keychain
- Bulk snapshot creation and deletion
- Smart snapshot chain detection
- Auto-reconnect capabilities
- Visual indicators for:
  - Snapshot chains (parent/child relationships)
  - Aged snapshots (> 3 business days)
- Copy functionality for VM names and snapshot details
- Progress tracking for long-running operations:
  - Visual progress bars for all operations
  - Numeric progress indicators with percentage
  - Status updates during long operations
- Configurable auto-connect settings

## Requirements

- Python 3.6+
- PyQt6
- pyVmomi (VMware SDK for Python)
- keyring

Install dependencies using:

## Usage

### Connecting to vCenter

1. Click "Add vCenter" to connect to a vCenter server
2. Enter the hostname, username, and password
3. Optionally save credentials securely in your system keychain

### Creating Snapshots

1. Click "Create Snapshots"
2. Enter server names (one per line)
3. Provide a snapshot description
4. Choose whether to include memory in the snapshot
5. Click "Create Snapshots" to begin the process

### Managing Snapshots

- Use the main view to see all snapshots across connected vCenters
- Check boxes next to snapshots you want to delete
- Click "Delete Selected" to remove chosen snapshots
- Right-click for additional options
- Double-click cells to copy content

### Auto-Connect Feature

- Configure auto-connect settings in the Settings menu
- Saved credentials are stored securely in your system keychain
- Automatic reconnection attempts if connection is lost

## Security Features

- Passwords are stored securely in the system keychain:
  - macOS: Keychain
  - Windows: Credential Manager
  - Linux: Secret Service

## Development

Built using:
- Python 3.x
- PyQt6 for the GUI
- pyVmomi for VMware integration
- keyring for secure credential storage


## Author

Christian Salas

## Support

For issues, please file a bug report in the GitHub repository.

---

*Note: This tool is not affiliated with or endorsed by VMware, Inc.*