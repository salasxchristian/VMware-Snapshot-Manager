import sys
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QPushButton, 
                            QLabel, QVBoxLayout, QHBoxLayout, QTreeWidget, 
                            QTreeWidgetItem, QDialog, QLineEdit, QGridLayout,
                            QCheckBox, QMessageBox, QComboBox, QFrame,
                            QTreeWidgetItemIterator, QMenu, QTextEdit, QProgressBar)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer, QMimeData
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim, vmodl
import ssl
import socket
import os
import json
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta, timezone
import urllib3
import time
from PyQt6.QtGui import QColor, QBrush, QIcon
import keyring
from PyQt6.QtCore import QSettings
import getpass
import re
from snapshot_filters import SnapshotFilterPanel
from version import __version__

# Built by Christian Salas

def format_vmware_time(vmware_datetime):
    """
    Convert VMware's UTC datetime to local timezone and format as string.
    
    Args:
        vmware_datetime: VMware createTime datetime object (assumed to be UTC)
        
    Returns:
        str: Formatted datetime string in local timezone ('YYYY-MM-DD HH:MM')
    """
    # VMware createTime appears to be in UTC, convert to local timezone
    if vmware_datetime.tzinfo is None:
        # Treat as UTC if no timezone info
        vmware_datetime = vmware_datetime.replace(tzinfo=timezone.utc)
    
    # Convert to local timezone
    local_time = vmware_datetime.astimezone()
    
    # Format as string
    return local_time.strftime('%Y-%m-%d %H:%M')

class ProgressTracker:
    """Standardized progress tracking for all operations"""
    @staticmethod
    def emit_progress(signal, current, total, operation, details=""):
        """Emit standardized progress signal"""
        if details:
            message = f"{operation}: {details} ({current}/{total})"
        else:
            message = f"{operation} ({current}/{total})"
        signal.emit(current, total, message)

class SnapshotFetchWorker(QThread):
    """Worker thread for fetching snapshots"""
    finished = pyqtSignal()
    progress = pyqtSignal(int, int, str)  # completed, total, message
    snapshot_found = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, vcenter_connections):
        super().__init__()
        self.vcenter_connections = vcenter_connections

    def run(self):
        try:
            total_vcenters = len(self.vcenter_connections)
            completed_vcenters = 0
            
            for hostname, si in self.vcenter_connections.items():
                ProgressTracker.emit_progress(
                    self.progress, completed_vcenters, total_vcenters,
                    "Connecting", f"{hostname}"
                )
                
                content = si.RetrieveContent()
                container = content.viewManager.CreateContainerView(
                    content.rootFolder, [vim.VirtualMachine], True
                )
                
                # Count VMs with snapshots for more detailed progress
                snapshot_vms = 0
                processed_vms = 0
                
                # First count VMs with snapshots
                for vm in container.view:
                    if vm.snapshot:
                        snapshot_vms += 1
                
                if snapshot_vms > 0:
                    # Now process VMs with progress updates
                    for vm in container.view:
                        if vm.snapshot:
                            processed_vms += 1
                            ProgressTracker.emit_progress(
                                self.progress, processed_vms, snapshot_vms,
                                "Processing", f"{vm.name}"
                            )
                            
                            for snapshot in self.get_snapshots(vm.snapshot.rootSnapshotList):
                                # Get creator information from snapshot description
                                # VMware snapshots don't have a built-in createdBy property
                                created_by = self.extract_creator_from_description(snapshot.description)
                                
                                self.snapshot_found.emit({
                                    'vm_name': vm.name,
                                    'vcenter': hostname,
                                    'name': snapshot.name,
                                    'created': format_vmware_time(snapshot.createTime),
                                    'created_by': created_by,
                                    'description': snapshot.description or '',
                                    'snapshot': snapshot,
                                    'vm': vm,
                                    'has_children': bool(snapshot.childSnapshotList),
                                    'is_child': hasattr(snapshot, 'parent') and snapshot.parent is not None
                                })
                
                container.Destroy()
                completed_vcenters += 1
            
            # Final progress update
            ProgressTracker.emit_progress(
                self.progress, total_vcenters, total_vcenters,
                "Complete", "Snapshots retrieved"
            )
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

    def get_snapshots(self, snapshots):
        result = []
        for snapshot in snapshots:
            result.append(snapshot)
            result.extend(self.get_snapshots(snapshot.childSnapshotList))
        return result
    
    def extract_creator_from_description(self, description):
        """
        Extract creator information from snapshot description.
        VMware snapshots don't have a built-in 'createdBy' property,
        so we need to parse it from the description field.
        """
        if not description:
            return 'Unknown'
        
        # Look for patterns like "Created by: username" or "(Created by: username)"
        patterns = [
            r'\(Created by:\s*([^)]+)\)',  # (Created by: username)
            r'Created by:\s*([^\n,;]+)',   # Created by: username
            r'\[Created by:\s*([^\]]+)\]', # [Created by: username]
            r'User:\s*([^\n,;]+)',         # User: username
        ]
        
        for pattern in patterns:
            match = re.search(pattern, description, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        return 'Unknown'
    
    def extract_creator_from_description(self, description):
        """
        Extract creator information from snapshot description.
        
        VMware snapshots don't have a built-in createdBy property,
        so we look for creator information in the description field.
        
        Args:
            description (str): The snapshot description
            
        Returns:
            str: The username who created the snapshot, or 'Unknown'
        """
        if not description:
            return 'Unknown'
        
        import re
        
        # Look for patterns like "Created by: username" or "(Created by: username)"
        patterns = [
            r'Created by:\s*(\w+)',
            r'\(Created by:\s*(\w+)\)',
            r'User:\s*(\w+)',
            r'By:\s*(\w+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, description, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return 'Unknown'

class AddVCenterDialog(QDialog):
    def __init__(self, saved_servers, config_manager, parent=None):
        super().__init__(parent)
        self.saved_servers = saved_servers
        self.config_manager = config_manager
        self.result = None
        
        self.setWindowTitle("Add vCenter Connection")
        self.setModal(True)
        self.resize(400, 250)
        
        # Load and apply last window position
        settings = QSettings()
        geometry = settings.value("AddVCenterDialogGeometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            # Center relative to parent if no saved position
            if parent:
                parent_geo = parent.geometry()
                x = parent_geo.x() + (parent_geo.width() - self.width()) // 2
                y = parent_geo.y() + (parent_geo.height() - self.height()) // 2
                self.move(x, y)
        
        # Fix for macOS focus issues
        self.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, True)
        if sys.platform == "darwin":  # macOS specific
            self.setWindowModality(Qt.WindowModality.WindowModal)
        
        layout = QGridLayout(self)
        
        # Server selection
        layout.addWidget(QLabel("Saved Servers:"), 0, 0)
        self.server_combo = QComboBox()
        self.server_combo.addItems([''] + list(saved_servers.keys()))  # Add empty option
        self.server_combo.activated.connect(self.on_server_selected)
        layout.addWidget(self.server_combo, 0, 1)
        
        # Connection details
        layout.addWidget(QLabel("Hostname:"), 1, 0)
        self.hostname = QLineEdit()
        layout.addWidget(self.hostname, 1, 1)
        
        layout.addWidget(QLabel("Username:"), 2, 0)
        self.username = QLineEdit()
        layout.addWidget(self.username, 2, 1)
        
        layout.addWidget(QLabel("Password:"), 3, 0)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.password, 3, 1)
        
        # Remember checkbox
        self.save_check = QCheckBox("Remember server credentials (passwords stored securely in system keychain)")
        self.save_check.setChecked(True)
        layout.addWidget(self.save_check, 4, 0, 1, 2)
        
        # Add info label about security
        info_text = ("Note: Passwords are stored securely in your system's keychain\n"
                    "(macOS Keychain, Windows Credential Manager, or Linux Secret Service)")
        info_label = QLabel(info_text)
        info_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(info_label, 5, 0, 1, 2)
        
        # Buttons
        button_box = QHBoxLayout()
        connect_btn = QPushButton("Connect")
        connect_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        
        button_box.addWidget(connect_btn)
        button_box.addWidget(cancel_btn)
        layout.addLayout(button_box, 6, 0, 1, 2)

    def on_server_selected(self, index):
        """Auto-fill saved server details and password"""
        hostname = self.server_combo.currentText()
        if hostname and hostname in self.saved_servers:
            username = self.saved_servers[hostname]
            self.hostname.setText(hostname)
            self.username.setText(username)
            
            # Try to get saved password
            password = self.config_manager.get_password(hostname, username)
            if password:
                self.password.setText(password)
            
            self.password.setFocus()

    def get_data(self):
        return {
            'hostname': self.hostname.text(),
            'username': self.username.text(),
            'password': self.password.text(),
            'save': self.save_check.isChecked()
        }

    def closeEvent(self, event):
        """Save window position when closing"""
        settings = QSettings()
        settings.setValue("AddVCenterDialogGeometry", self.saveGeometry())
        super().closeEvent(event)

class SnapshotDeleteWorker(QThread):
    """Worker thread for deleting snapshots"""
    progress = pyqtSignal(int, int, str)  # completed, total, message
    finished = pyqtSignal()
    error = pyqtSignal(str)
    item_complete = pyqtSignal(QTreeWidgetItem)

    def __init__(self, items_to_delete):
        super().__init__()
        self.items_to_delete = items_to_delete

    def run(self):
        total = len(self.items_to_delete)
        completed = 0
        active_tasks = {}  # Store active deletion tasks
        
        # Start all deletion tasks
        for item, data in self.items_to_delete:
            try:
                ProgressTracker.emit_progress(
                    self.progress, completed, total,
                    "Deleting", f"{data['vm_name']}"
                )
                
                # Get the VM and snapshot objects
                snapshot = data['snapshot']
                
                # Create deletion task
                task = snapshot.snapshot.RemoveSnapshot_Task(removeChildren=False)
                active_tasks[task] = (item, data)
                
            except Exception as e:
                self.error.emit(f"Error starting deletion of {data['name']}: {str(e)}")
        
        # Monitor all tasks until completion
        while active_tasks:
            total_progress = 0
            
            for task in list(active_tasks.keys()):
                item, data = active_tasks[task]
                try:
                    if task.info.state == vim.TaskInfo.State.success:
                        self.item_complete.emit(item)
                        completed += 1
                        del active_tasks[task]
                    elif task.info.state == vim.TaskInfo.State.error:
                        self.error.emit(f"Failed to delete {data['name']}: {task.info.error.msg}")
                        del active_tasks[task]
                    else:
                        # Task still in progress, add to total progress
                        task_progress = task.info.progress or 0
                        total_progress += task_progress
                except Exception as e:
                    self.error.emit(f"Error monitoring {data['name']}: {str(e)}")
                    del active_tasks[task]
            
            # Calculate and show overall progress
            if active_tasks:
                overall_progress = (completed * 100 + total_progress) / total
                ProgressTracker.emit_progress(
                    self.progress, completed, total,
                    "Deleting", f"{overall_progress:.0f}%"
                )
            
            # Small delay before next check
            time.sleep(0.5)
        
        ProgressTracker.emit_progress(
            self.progress, total, total,
            "Complete", "All deleted"
        )
        self.finished.emit()

class SnapshotManagerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"pySnap - VMware Snapshot Manager v{__version__}")
        self.resize(1200, 600)
        
        # Load and apply last window position
        settings = QSettings()
        geometry = settings.value("WindowGeometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            # Center the window if no saved position exists
            self.center_window(self)
        
        # Fix for macOS focus issues
        self.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, True)
        if sys.platform == "darwin":  # macOS specific
            self.setUnifiedTitleAndToolBarOnMac(True)
        
        # Set application and window icon
        icon_path = os.path.join(os.path.dirname(__file__), 'icons', 'app_icon.png')
        if os.path.exists(icon_path):
            app_icon = QIcon(icon_path)
            self.setWindowIcon(app_icon)
            QApplication.setWindowIcon(app_icon)
        
        # Initialize variables
        self.vcenter_connections = {}
        self.snapshots = {}
        self.setup_logging()
        self.logger = logging.getLogger('pySnap')
        self.config_manager = ConfigManager()
        self.saved_servers = self.config_manager.load_servers()
        
        # Add connection monitoring timer
        self.connection_timer = QTimer(self)
        self.connection_timer.timeout.connect(self.check_connections)
        self.connection_timer.start(300000)  # Check every 5 minutes
        
        # Store credentials for reconnection
        self.active_credentials = {}  # Store credentials for active connections
        
        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Connection management section
        conn_frame = QFrame()
        conn_frame.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Sunken)
        conn_layout = QHBoxLayout(conn_frame)
        
        self.add_conn_btn = QPushButton("Add vCenter")
        self.add_conn_btn.clicked.connect(self.add_vcenter)
        
        self.auto_conn_btn = QPushButton("Auto-Connect")
        self.auto_conn_btn.clicked.connect(self.manual_auto_connect)
        self.auto_conn_btn.setEnabled(len(self.saved_servers) > 0)
        
        self.clear_conn_btn = QPushButton("Clear Connections")
        self.clear_conn_btn.clicked.connect(self.clear_connections)
        self.clear_conn_btn.setEnabled(False)
        
        self.conn_label = QLabel("No active connections")
        
        # Add checkbox for filtering patching snapshots
        self.patch_filter_checkbox = QCheckBox("Show 'Monthly OS Patching' snapshots only")
        self.patch_filter_checkbox.setToolTip("When checked, only snapshots containing 'patch' in the name are fetched")
        
        # Load saved state from settings
        settings = QSettings()
        patch_filter_enabled = settings.value("PatchFilterEnabled", True, type=bool)
        self.patch_filter_checkbox.setChecked(patch_filter_enabled)
        
        # Connect to filter panel and save state when changed
        self.patch_filter_checkbox.stateChanged.connect(self.save_patch_filter_state)
        self.patch_filter_checkbox.stateChanged.connect(self.sync_patch_filter_to_panel)
        self.patch_filter_checkbox.stateChanged.connect(self.apply_filters)
        
        conn_layout.addWidget(self.add_conn_btn)
        conn_layout.addWidget(self.auto_conn_btn)
        conn_layout.addWidget(self.clear_conn_btn)
        conn_layout.addWidget(self.conn_label)
        conn_layout.addStretch()
        conn_layout.addWidget(self.patch_filter_checkbox)
        
        # Filter panel
        self.filter_panel = SnapshotFilterPanel()
        self.filter_panel.filters_changed.connect(self.apply_filters)
        self.filter_panel.filters_changed.connect(self.sync_patch_filter_from_panel)
        self.filter_panel.filters_changed.connect(self.update_old_snapshots_label)
        
        # Sync the patching filter with the main checkbox
        self.filter_panel.set_patching_filter(patch_filter_enabled)
        
        # Reset all filters to defaults on app launch
        self.filter_panel.reset_all_filters_to_defaults()
        
        # Update the color legend label
        self.update_old_snapshots_label()
        
        # Tree widget for snapshots
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Select", "VM Name", "vCenter", "Snapshot Name", "Created", "Created By", "Description", "Snapshot Type"])
        self.tree.setSortingEnabled(True)
        
        # Disable row selection, only allow checkbox interaction
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        
        # Connect to item clicked for checkbox handling
        self.tree.itemClicked.connect(self.on_item_clicked)
        
        # Set default sorting to Created column (index 4) in ascending order
        self.tree.sortByColumn(4, Qt.SortOrder.AscendingOrder)
        
        # Enable context menu for tree widget
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)
        
        # Connect double-click handler
        self.tree.itemDoubleClicked.connect(self.on_item_double_clicked)
        
        # Button frame
        button_frame = QWidget()
        button_layout = QHBoxLayout(button_frame)
        
        # Set fixed width for all buttons
        button_width = 150  # Fixed width for all action buttons
        
        self.create_button = QPushButton("Create Snapshots")
        self.create_button.setFixedWidth(button_width)
        self.create_button.clicked.connect(self.create_snapshots)
        
        self.fetch_button = QPushButton("Get Snapshots")  # Shortened text
        self.fetch_button.setFixedWidth(button_width)
        self.fetch_button.clicked.connect(self.start_fetch)
        self.fetch_button.setEnabled(False)
        
        self.delete_button = QPushButton("Delete Selected")
        self.delete_button.setFixedWidth(button_width)
        self.delete_button.clicked.connect(self.delete_selected)
        self.delete_button.setEnabled(False)
        
        # Add buttons with some spacing
        button_layout.addStretch()  # Push buttons to center
        button_layout.addWidget(self.create_button)
        button_layout.addSpacing(10)  # Add space between buttons
        button_layout.addWidget(self.fetch_button)
        button_layout.addSpacing(10)
        button_layout.addWidget(self.delete_button)
        button_layout.addStretch()  # Push buttons to center
        
        # Add highlighting info label with color legend
        highlight_frame = QFrame()
        highlight_layout = QHBoxLayout(highlight_frame)
        
        # Create color boxes with labels
        def create_color_box(color, text, add_help_button=False):
            box_layout = QHBoxLayout()
            color_box = QLabel()
            color_box.setFixedSize(16, 16)
            color_box.setStyleSheet(f"background-color: {color}; border: 1px solid #666;")
            label = QLabel(text)
            box_layout.addWidget(color_box)
            box_layout.addWidget(label)
            
            if add_help_button:
                # Add help button for chain snapshots
                help_button = QPushButton("?")
                help_button.setFixedSize(20, 20)
                help_button.setStyleSheet("""
                    QPushButton {
                        background-color: #f0f0f0;
                        border: 1px solid #999;
                        border-radius: 10px;
                        font-size: 12px;
                        font-weight: bold;
                        color: #666;
                    }
                    QPushButton:hover {
                        background-color: #e0e0e0;
                        border-color: #666;
                    }
                """)
                help_button.clicked.connect(lambda: self.show_chain_snapshot_help())
                box_layout.addWidget(help_button)
            
            box_layout.addStretch()
            return box_layout

        # Add color legends with help button for chain snapshots
        child_snapshot_layout = create_color_box("#CCCCCC", "Chain Snapshots", add_help_button=True)
        highlight_layout.addLayout(child_snapshot_layout)
        
        # Create dynamic label for old snapshots that updates with filter settings
        self.old_snapshots_layout = create_color_box("#FFFF99", "Snapshots > 3 business days")
        highlight_layout.addLayout(self.old_snapshots_layout)
        highlight_layout.addStretch()
        
        # Replace the old highlight info with the new frame
        main_layout.addWidget(conn_frame)
        main_layout.addWidget(self.tree)
        main_layout.addWidget(highlight_frame)
        main_layout.addWidget(button_frame)
        
        # Status bar
        status_frame = QWidget()
        status_layout = QHBoxLayout(status_frame)
        
        self.status_label = QLabel("Ready")
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(150)  # Compact size
        self.progress_bar.setMinimumWidth(120)  # Compact minimum width
        self.progress_bar.setTextVisible(True)  # Show percentage text
        self.progress_bar.setFormat("%p%")     # Format as percentage
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #AAAAAA;
                border-radius: 4px;
                background: #F0F0F0;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #4682B4;  /* Steel Blue */
                border-radius: 3px;
            }
        """)
        self.progress_bar.hide()  # Hidden by default
        self.counter_label = QLabel("Snapshots: 0")
        
        status_layout.addWidget(self.progress_bar)
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        status_layout.addWidget(self.counter_label)
        
        # Add all sections to main layout
        main_layout.addWidget(conn_frame)
        main_layout.addWidget(self.filter_panel)
        main_layout.addWidget(self.tree)
        main_layout.addWidget(highlight_frame)
        main_layout.addWidget(button_frame)
        main_layout.addWidget(status_frame)

        # Add column widths
        self.tree.setColumnWidth(0, 50)   # Checkbox column
        self.tree.setColumnWidth(1, 180)  # VM Name
        self.tree.setColumnWidth(2, 180)  # vCenter
        self.tree.setColumnWidth(3, 180)  # Snapshot Name
        self.tree.setColumnWidth(4, 130)  # Created
        self.tree.setColumnWidth(5, 120)  # Created By
        self.tree.setColumnWidth(6, 250)  # Description
        self.tree.setColumnWidth(7, 150)  # Snapshot Type column

        # After loading saved_servers
        self.check_auto_connect()

        # Settings menu removed - auto-connect is now manual only

    def get_snapshots(self):
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            json_path = os.path.join(script_dir, 'snapshots.json')
            
            if not os.path.exists(json_path):
                messagebox.showerror("Error", "snapshots.json not found. Please run export_snapshots.ps1 first.")
                return []
                
            with open(json_path, 'r') as f:
                data = json.load(f)
                
            # Ensure we always return a list
            if not isinstance(data, list):
                data = [data]
            return data
            
        except json.JSONDecodeError as e:
            messagebox.showerror("Error", f"Failed to parse JSON file:\n{e}")
            return []
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read snapshots:\n{e}")
            return []

    def refresh_snapshots(self):
        self.status_var.set("Refreshing snapshots...")
        self.root.update()
        
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        snapshots = self.get_snapshots()
        for snap in snapshots:
            status = "Ineligible (Chain)" if snap['HasChildren'] or snap['IsChild'] else "Eligible"
            
            # Handle different datetime formats
            try:
                # Try parsing with timezone offset
                created_date = datetime.datetime.strptime(
                    snap['Created'].split('.')[0], 
                    '%Y-%m-%dT%H:%M:%S'
                ).strftime('%Y-%m-%d %H:%M')
            except ValueError:
                try:
                    # Fallback to UTC format
                    created_date = datetime.datetime.strptime(
                        snap['Created'], 
                        '%Y-%m-%dT%H:%M:%S.%fZ'
                    ).strftime('%Y-%m-%d %H:%M')
                except ValueError:
                    # If all else fails, just show the raw date
                    created_date = snap['Created']
            
            self.tree.insert("", Qt.ItemModelRole.End, values=(
                snap['VMName'],
                snap['vCenter'],
                snap['Name'],
                created_date,
                f"{snap['SizeMB']:.2f}",
                status
            ))
        
        self.status_var.set(f"Found {len(snapshots)} snapshots")

    def delete_selected(self):
        """Delete selected snapshots"""
        selected_items = []
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            if item.checkState(0) == Qt.CheckState.Checked:
                snapshot_id = item.data(0, Qt.ItemDataRole.UserRole)
                if snapshot_id in self.snapshots:
                    selected_items.append((item, self.snapshots[snapshot_id]))
            iterator += 1
        
        if not selected_items:
            QMessageBox.warning(self, "Warning", "No snapshots selected")
            return
        
        # Group snapshots by vCenter for better organization
        by_vcenter = {}
        for item, data in selected_items:
            vcenter = data['vcenter']
            if vcenter not in by_vcenter:
                by_vcenter[vcenter] = []
            by_vcenter[vcenter].append(data)
        
        # Create enhanced confirmation dialog
        confirm_msg = (
            f"You are about to delete {len(selected_items)} snapshot{'s' if len(selected_items) > 1 else ''}.\n"
            "Please review the following snapshots carefully:\n"
        )
        
        # Create custom confirmation dialog with scrollable area
        dialog = QDialog(self)
        dialog.setWindowTitle("Confirm Snapshot Deletion")
        dialog.setModal(True)
        dialog.resize(600, 400)  # Set reasonable default size
        
        layout = QVBoxLayout(dialog)
        
        # Warning icon and message
        warning_layout = QHBoxLayout()
        warning_icon = QLabel("⚠️")
        warning_icon.setStyleSheet("font-size: 24px;")
        warning_text = QLabel(confirm_msg)
        warning_layout.addWidget(warning_icon)
        warning_layout.addWidget(warning_text, 1)
        layout.addLayout(warning_layout)
        
        # Scrollable text area for snapshot details
        text_area = QTextEdit()
        text_area.setReadOnly(True)
        text_area.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        
        # Build detailed message
        details = ""
        for vcenter, snapshots in by_vcenter.items():
            details += f"\nvCenter: {vcenter}"
            for data in snapshots:
                details += f"\n• VM: {data['vm_name']}"
                details += f"\n  ├ Snapshot: {data['name']}"
                details += f"\n  ├ Created: {data['created']}"
                details += f"\n  └ Age: {self.get_business_days(datetime.strptime(data['created'], '%Y-%m-%d %H:%M'), datetime.now())} business days"
                details += "\n"
        
        details += "\nWARNING: This action cannot be undone!"
        text_area.setText(details)
        layout.addWidget(text_area)
        
        # Buttons
        button_box = QHBoxLayout()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        
        delete_btn = QPushButton("Delete Snapshots")
        delete_btn.clicked.connect(dialog.accept)
        delete_btn.setStyleSheet("QPushButton { color: red; }")
        
        button_box.addStretch()  # Add stretch before buttons to right-align them
        button_box.addWidget(cancel_btn)
        button_box.addWidget(delete_btn)
        layout.addLayout(button_box)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.start_delete(selected_items)

    def setup_logging(self):
        """Configure application logging"""
        log_file = os.path.join(os.path.expanduser("~"), "pysnap.log")
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # File handler with rotation
        file_handler = RotatingFileHandler(
            log_file, maxBytes=1024*1024, backupCount=5
        )
        file_handler.setFormatter(formatter)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        
        # Setup root logger
        logger = logging.getLogger('pySnap')
        logger.setLevel(logging.INFO)
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    def on_item_clicked(self, item, column):
        """Handle tree item clicks"""
        if column == 0:  # Only handle clicks in the checkbox column
            # Let Qt handle the checkbox state toggle naturally
            pass
            
            # Count checked items and update delete button
            checked_count = 0
            iterator = QTreeWidgetItemIterator(self.tree)
            while iterator.value():
                if iterator.value().checkState(0) == Qt.CheckState.Checked:
                    checked_count += 1
                iterator += 1
            
            # Update delete button text and enabled state
            if checked_count > 0:
                self.delete_button.setText(f"Delete Selected ({checked_count})")
                self.delete_button.setEnabled(True)
            else:
                self.delete_button.setText("Delete Selected")
                self.delete_button.setEnabled(False)
        else:
            # Prevent selection when clicking other columns
            self.tree.clearSelection()

    def add_vcenter(self):
        """Show dialog to add new vCenter connection"""
        dialog = AddVCenterDialog(self.saved_servers, self.config_manager, self)
        self.center_window(dialog)  # Center the dialog
        if dialog.exec():
            data = dialog.get_data()
            try:
                # Show connection status without progress bar
                self.status_label.setText(f"Connecting to {data['hostname']}...")
                
                # Create SSL context that ignores verification
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                
                # Disable SSL verification warnings
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                
                # Set temporary socket timeout for this connection
                old_timeout = socket.getdefaulttimeout()
                socket.setdefaulttimeout(10.0)
                
                try:
                    si = SmartConnect(
                        host=data['hostname'],
                        user=data['username'],
                        pwd=data['password'],
                        sslContext=context,
                        disableSslCertValidation=True
                    )
                finally:
                    # Restore original timeout
                    socket.setdefaulttimeout(old_timeout)
                
                self.status_label.setText(f"Connected to {data['hostname']}, initializing...")
                
                if si:
                    self.vcenter_connections[data['hostname']] = si
                    self.active_credentials[data['hostname']] = {
                        'username': data['username'],
                        'password': data['password']
                    }
                    # Save credentials if requested
                    if data['save']:
                        self.status_label.setText("Saving credentials...")
                        
                        self.saved_servers[data['hostname']] = data['username']
                        self.config_manager.save_servers(self.saved_servers)
                        self.config_manager.save_password(
                            data['hostname'],
                            data['username'],
                            data['password']
                        )
                    
                    self.status_label.setText(f"Successfully connected to {data['hostname']}")
                    
                    # Update UI and reset status after a delay
                    self.update_connection_status()
                    
                    # Reset status after a short delay
                    QTimer.singleShot(2000, lambda: self.status_label.setText("Ready"))
                    
            except Exception as e:
                self.status_label.setText("Ready")
                QMessageBox.critical(self, "Connection Error", str(e))
                self.logger.error(f"Failed to connect to {data['hostname']}: {str(e)}")

    def clear_connections(self):
        """Clear all vCenter connections"""
        for hostname, si in self.vcenter_connections.items():
            try:
                Disconnect(si)
            except:
                pass
        self.vcenter_connections.clear()
        self.active_credentials.clear()  # Clear stored credentials
        self.update_connection_status()

    def update_connection_status(self):
        """Update the connection status label"""
        if not self.vcenter_connections:
            self.conn_label.setText("No active connections")
            self.clear_conn_btn.setEnabled(False)
            self.fetch_button.setEnabled(False)
            self.delete_button.setEnabled(False)
        else:
            status_text = ""
            for hostname in self.vcenter_connections:
                try:
                    # Test connection
                    self.vcenter_connections[hostname].CurrentTime()
                    status_text += f"🟢 {hostname}  "  # Green circle for success
                except:
                    status_text += f"🔴 {hostname}  "  # Red circle for failure
            
            self.conn_label.setText(f"Connected to: {status_text}")
            self.clear_conn_btn.setEnabled(True)
            self.fetch_button.setEnabled(True)

    def start_fetch(self):
        """Start fetching snapshots in background"""
        self.tree.clear()
        self.snapshots.clear()  # Clear snapshot data
        self.clear_filters_on_refresh()  # Clear filters
        self.fetch_button.setEnabled(False)
        self.delete_button.setText("Delete Selected")  # Reset delete button text
        
        # Show initial progress
        self.progress_bar.show()
        self.progress_bar.setValue(0)
        self.status_label.setText("Fetching snapshots...")
        
        self.fetch_worker = SnapshotFetchWorker(self.vcenter_connections)
        self.fetch_worker.progress.connect(self.update_progress)
        self.fetch_worker.snapshot_found.connect(self.add_snapshot_to_tree)
        self.fetch_worker.error.connect(self.on_fetch_error)
        self.fetch_worker.finished.connect(self.on_fetch_complete)
        self.fetch_worker.start()

    def add_snapshot_to_tree(self, data):
        """Add a snapshot to the tree widget"""
        item = QTreeWidgetItem(self.tree)
        
        # Check if snapshot is part of a chain
        is_in_chain = data['has_children'] or data['is_child']
        
        if is_in_chain:
            # Disable checkbox and add warning style
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEnabled)  # Don't add ItemIsUserCheckable
            warning_color = QColor(211, 211, 211)  # Light gray
            warning_text = QColor(128, 128, 128)  # Gray text
            
            for column in range(8):
                item.setBackground(column, QBrush(warning_color))
                item.setForeground(column, QBrush(warning_text))
            
            # Add warning tooltip
            chain_status = []
            if data['has_children']:
                chain_status.append("Has child snapshots")
            if data['is_child']:
                chain_status.append("Is a child snapshot")
            
            warning_text = "Cannot delete: " + " and ".join(chain_status)
            warning_text += "\n\nChain snapshots must be deleted through vSphere Client because:"
            warning_text += "\n• They have dependencies that require special handling"
            warning_text += "\n• Improper deletion can corrupt VM data"
            warning_text += "\n• VMware needs to consolidate disk changes properly"
            item.setToolTip(0, warning_text)
        else:
            # Normal snapshot handling
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            item.setCheckState(0, Qt.CheckState.Unchecked)
        
        # Set text for other columns
        item.setText(1, data['vm_name'])
        item.setText(2, data['vcenter'])
        item.setText(3, data['name'])
        item.setText(4, data['created'])
        item.setText(5, data.get('created_by', 'Unknown'))  # Add created by column
        item.setText(6, data.get('description', ''))  # Add description column
        
        # Add chain status column
        if is_in_chain:
            if data['has_children'] and data['is_child']:
                chain_status = "Part of Chain (Middle)"
            elif data['has_children']:
                chain_status = "Has Child Snapshots (Delete Manually)"
            else:  # is_child
                chain_status = "Child Snapshot"
        else:
            chain_status = "Independent Snapshot"  # Changed from "Safe to Delete"
        item.setText(7, chain_status)
        
        # Only apply age highlighting if NOT part of a chain (chain highlighting takes precedence)
        if not is_in_chain:
            # Check if snapshot is older than the configured threshold
            created_date = datetime.strptime(data['created'], '%Y-%m-%d %H:%M')
            current_date = datetime.now()
            
            # Get the age threshold and day type from the filter panel
            age_threshold = self.filter_panel.get_age_threshold()
            day_type = self.filter_panel.get_day_type()
            
            # Calculate days between dates based on selected type
            if day_type == "business days":
                days_old = self.get_business_days(created_date, current_date)
            else:  # calendar days
                days_old = self.get_calendar_days(created_date, current_date)
            
            if days_old > age_threshold:
                # Highlight old snapshots with yellow colors
                background_color = QColor(255, 255, 200)  # Light yellow
                text_color = QColor(139, 69, 19)  # Saddle brown (dark brown)
                
                for column in range(8):
                    item.setBackground(column, QBrush(background_color))
                    item.setForeground(column, QBrush(text_color))
                
                # Add tooltip with age information
                age_text = f"Snapshot is {days_old} {day_type} old (threshold: {age_threshold} {day_type})"
                item.setToolTip(0, age_text)
        
        # Generate a unique ID for the snapshot
        snapshot_id = f"{data['vcenter']}_{data['vm_name']}_{data['name']}"
        
        # Store the ID in the item's data
        item.setData(0, Qt.ItemDataRole.UserRole, snapshot_id)
        
        # Store snapshot data using the ID
        self.snapshots[snapshot_id] = data
        
        # Update counter
        self.update_snapshot_counter()
        
        # Update filter dropdown options
        self.filter_panel.update_dropdown_options(self.snapshots)

    def get_business_days(self, start_date, end_date):
        """Calculate number of business days between two dates"""
        current = start_date
        business_days = 0
        
        while current <= end_date:
            # Monday = 0, Sunday = 6
            if current.weekday() < 5:  # Monday to Friday
                business_days += 1
            current += timedelta(days=1)
            
        return business_days
    
    def get_calendar_days(self, start_date, end_date):
        """Calculate number of calendar days between two dates"""
        return (end_date - start_date).days

    def on_fetch_error(self, error_msg):
        """Handle fetch errors"""
        QMessageBox.warning(self, "Error", f"Failed to fetch snapshots: {error_msg}")
        self.fetch_button.setEnabled(True)

    def on_fetch_complete(self):
        """Handle fetch completion"""
        self.reset_progress()
        self.fetch_button.setEnabled(True)
        self.delete_button.setEnabled(True)
        
        # Update filter dropdown options with new data
        self.filter_panel.update_dropdown_options(self.snapshots)

    def start_delete(self, selected_items):
        """Start deletion process"""
        self.fetch_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        
        # Show initial progress
        self.progress_bar.show()
        self.progress_bar.setValue(0)
        self.status_label.setText("Starting snapshot deletion...")
        
        self.delete_worker = SnapshotDeleteWorker(selected_items)
        self.delete_worker.progress.connect(self.update_progress)
        self.delete_worker.error.connect(lambda msg: QMessageBox.warning(self, "Error", msg))
        self.delete_worker.item_complete.connect(self.remove_deleted_item)
        self.delete_worker.finished.connect(self.on_delete_complete)
        self.delete_worker.start()

    def remove_deleted_item(self, item):
        """Remove a successfully deleted item from the tree"""
        snapshot_id = item.data(0, Qt.ItemDataRole.UserRole)
        if snapshot_id in self.snapshots:
            del self.snapshots[snapshot_id]
        self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
        self.update_snapshot_counter()
        
        # Reset delete button text after deletion
        self.delete_button.setText("Delete Selected")

    def on_delete_complete(self):
        """Handle deletion completion"""
        self.reset_progress()
        self.fetch_button.setEnabled(True)
        self.delete_button.setEnabled(True)

    def check_connections(self):
        """Check all connections and reconnect if needed"""
        reconnect_needed = []
        
        for hostname, si in list(self.vcenter_connections.items()):
            try:
                # Test connection by making a simple API call
                si.CurrentTime()
            except Exception as e:
                self.logger.warning(f"Connection to {hostname} lost: {str(e)}")
                
                # Add to reconnection list if we have credentials
                if hostname in self.active_credentials:
                    reconnect_needed.append(hostname)
                else:
                    # No credentials available, remove the connection
                    self.vcenter_connections.pop(hostname, None)
        
        # If reconnections needed, show status without progress
        if reconnect_needed:
            total = len(reconnect_needed)
            completed = 0
            
            for hostname in reconnect_needed:
                completed += 1
                self.status_label.setText(f"Reconnecting to {hostname}... ({completed}/{total})")
                
                try:
                    creds = self.active_credentials[hostname]
                    context = ssl.create_default_context()
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE
                    
                    new_si = SmartConnect(
                        host=hostname,
                        user=creds['username'],
                        pwd=creds['password'],
                        sslContext=context,
                        disableSslCertValidation=True
                    )
                    
                    if new_si:
                        self.vcenter_connections[hostname] = new_si
                        self.logger.info(f"Successfully reconnected to {hostname}")
                    else:
                        self.logger.error(f"Failed to reconnect to {hostname}")
                        # Remove failed connection
                        self.vcenter_connections.pop(hostname, None)
                        self.active_credentials.pop(hostname, None)
                        
                except Exception as reconnect_error:
                    self.logger.error(f"Failed to reconnect to {hostname}: {str(reconnect_error)}")
                    # Remove failed connection
                    self.vcenter_connections.pop(hostname, None)
                    self.active_credentials.pop(hostname, None)
            
            # Reset status when done
            self.status_label.setText("Ready")
        
        # Update UI based on current connections
        self.update_connection_status()

    def show_context_menu(self, position):
        """Show context menu for tree widget"""
        item = self.tree.itemAt(position)
        if not item:
            return
            
        menu = QMenu(self)
        
        # Get the column that was clicked
        column = self.tree.header().logicalIndexAt(position.x())
        cell_text = item.text(column)
        
        # Create actions for copying
        copy_action = menu.addAction(f"Copy '{self.tree.headerItem().text(column)}'")
        copy_action.triggered.connect(lambda: self.copy_to_clipboard(cell_text))
        
        # Add action to copy VM name regardless of which column was clicked
        if column != 1:  # If not already on VM Name column
            vm_name = item.text(1)
            copy_vm_action = menu.addAction("Copy VM Name")
            copy_vm_action.triggered.connect(lambda: self.copy_to_clipboard(vm_name))
        
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def copy_to_clipboard(self, text):
        """Copy text to clipboard"""
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        self.status_label.setText(f"Copied to clipboard: {text}")
        
        # Reset status after 2 seconds
        QTimer.singleShot(2000, lambda: self.status_label.setText("Ready"))
    
    def get_current_vcenter_username(self):
        """
        Get the vCenter username from active credentials, stripping domain if present.
        Returns the first available username, or system user as fallback.
        """
        for hostname, credentials in self.active_credentials.items():
            username = credentials.get('username', '')
            if username:
                # Strip domain part (e.g., "csalas@vsphere.local" -> "csalas")
                if '@' in username:
                    return username.split('@')[0]
                # Strip domain part (e.g., "DOMAIN\\csalas" -> "csalas")
                elif '\\' in username:
                    return username.split('\\')[-1]
                else:
                    return username
        
        # Fallback to system username if no vCenter credentials available
        return getpass.getuser()

    def on_item_double_clicked(self, item, column):
        """Handle double-click to copy cell content"""
        if column != 0:  # Don't handle checkbox column
            text = item.text(column)
            QApplication.clipboard().setText(text)
            self.status_label.setText(f"Copied to clipboard: {text}")
            
            # Reset status after 2 seconds
            QTimer.singleShot(2000, lambda: self.status_label.setText("Ready"))

    def center_window(self, window):
        """Center a window on the screen"""
        screen = QApplication.primaryScreen().geometry()
        window_size = window.geometry()
        x = (screen.width() - window_size.width()) // 2
        y = (screen.height() - window_size.height()) // 2
        window.move(x, y)

    def create_snapshots(self):
        """Show dialog to create snapshots in bulk"""
        if not self.vcenter_connections:
            QMessageBox.warning(self, "Warning", "No active vCenter connections")
            return
            
        dialog = CreateSnapshotsDialog(self)
        if dialog.exec():
            data = dialog.get_data()
            if not data['servers']:
                QMessageBox.warning(self, "Warning", "No servers entered")
                return
            
            self.start_create_snapshots(data['servers'], data['description'], data['memory'])

    def start_create_snapshots(self, servers, description, memory=False):
        """Start snapshot creation process"""
        self.fetch_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        
        # Get the vCenter username for creator tracking
        vcenter_username = self.get_current_vcenter_username()
        
        self.create_worker = SnapshotCreateWorker(
            self.vcenter_connections, 
            servers, 
            description,
            memory,
            vcenter_username
        )
        self.create_worker.progress.connect(
            lambda completed, total, msg: self.update_progress(completed, total, msg)
        )
        self.create_worker.error.connect(lambda msg: QMessageBox.warning(self, "Errors Occurred", msg))
        self.create_worker.snapshot_created.connect(self.handle_created_snapshot)
        self.create_worker.finished.connect(self.on_create_complete)
        self.create_worker.start()
        
    def handle_created_snapshot(self, snapshot_data):
        """
        Handle newly created snapshots by adding them directly to the tree.
        This implements a caching strategy that avoids refetching all snapshots
        after creating new ones, which improves performance.
        
        Args:
            snapshot_data (dict): Dictionary containing snapshot details
        """
        # If we received a dict with full snapshot details, add it to the tree
        if isinstance(snapshot_data, dict) and 'vm_name' in snapshot_data and 'snapshot' in snapshot_data:
            self.add_snapshot_to_tree(snapshot_data)
            self.logger.info(f"Added new snapshot for {snapshot_data['vm_name']} to tree")
        # For backward compatibility with older versions
        elif isinstance(snapshot_data, dict) and 'vm_name' in snapshot_data:
            self.logger.info(f"Created snapshot for {snapshot_data['vm_name']}")
        else:
            self.logger.info(f"Created snapshot with unknown details")

    def on_create_complete(self):
        """
        Handle completion of snapshot creation.
        
        This method only resets UI elements and doesn't call start_fetch()
        as the snapshots have already been added to the tree via the 
        handle_created_snapshot method, implementing an efficient caching strategy.
        """
        self.reset_progress()
        self.fetch_button.setEnabled(True)
        self.delete_button.setEnabled(True)
        # No need to call start_fetch() as we've already added the snapshots to the tree

    def closeEvent(self, event):
        """Save window position when closing"""
        settings = QSettings()
        settings.setValue("WindowGeometry", self.saveGeometry())
        super().closeEvent(event)

    def update_progress(self, value, total, operation):
        """
        Update progress bar and status for any operation in the application.
        
        This is the standardized method for showing progress across all operations.
        All worker threads should emit progress signals in the format (value, total, message)
        and connect their signals to this method.
        
        Args:
            value (int): Current progress value
            total (int): Total steps required for completion
            operation (str): Description of the current operation
        """
        if total > 0:
            percentage = (value / total) * 100
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(value)
            self.progress_bar.show()
            self.status_label.setText(f"{operation}: {percentage:.1f}% ({value}/{total})")
        else:
            self.progress_bar.hide()
            self.status_label.setText(operation)

    def reset_progress(self):
        """
        Reset progress bar and status label to default state.
        
        This method should be called when an operation completes or is cancelled
        to ensure consistent UI state across the application.
        """
        self.progress_bar.hide()
        self.progress_bar.setValue(0)
        self.status_label.setText("Ready")

    def check_auto_connect(self):
        """Initialize without auto-connect on startup"""
        # Auto-connect is now manual via button only
        self.status_label.setText("Ready")

    def manual_auto_connect(self):
        """Manually trigger auto-connect via button click"""
        if not self.saved_servers:
            QMessageBox.information(self, "Info", "No saved servers to connect to.")
            return
        
        # Disable the button during connection
        self.auto_conn_btn.setEnabled(False)
        self.auto_conn_btn.setText("Connecting...")
        
        # Update connection label
        self.conn_label.setText("🔄 Auto-connecting to saved vCenters...")
        self.start_auto_connect_worker()

    def start_auto_connect_worker(self):
        """Start the auto-connect worker thread"""
        if not self.saved_servers:
            self.status_label.setText("Ready")
            return
            
        self.auto_connect_worker = AutoConnectWorker(self.saved_servers, self.config_manager)
        self.auto_connect_worker.progress.connect(self.update_auto_connect_status)
        self.auto_connect_worker.connection_made.connect(self.handle_auto_connection)
        self.auto_connect_worker.finished.connect(self.on_auto_connect_finished)
        self.auto_connect_worker.error.connect(self.on_auto_connect_error)
        self.auto_connect_worker.start()
    
    def update_auto_connect_status(self, message):
        """Update connection label during auto-connect"""
        self.conn_label.setText(f"🔄 {message}")
    
    def handle_auto_connection(self, hostname, si, credentials):
        """Handle successful auto-connection"""
        self.vcenter_connections[hostname] = si
        self.active_credentials[hostname] = credentials
        self.logger.info(f"Auto-connected to {hostname}")
    
    def on_auto_connect_finished(self):
        """Handle auto-connect completion"""
        self.update_connection_status()
        # Re-enable auto-connect button
        self.auto_conn_btn.setEnabled(True)
        self.auto_conn_btn.setText("Auto-Connect")
    
    def on_auto_connect_error(self, error_msg):
        """Handle auto-connect errors"""
        self.logger.error(error_msg)
        # Update status to show error briefly
        self.status_label.setText(f"Connection error - check log")
        # Reset status after 3 seconds
        QTimer.singleShot(3000, lambda: self.status_label.setText("Ready"))


    
    def apply_filters(self):
        """
        Apply current filters to the snapshot tree.
        This method is called whenever any filter changes.
        """
        # Check if tree exists (it might not during initialization)
        if not hasattr(self, 'tree') or self.tree is None:
            return
            
        root = self.tree.invisibleRootItem()
        visible_count = 0
        age_threshold = self.filter_panel.get_age_threshold()
        patching_only = self.patch_filter_checkbox.isChecked()
        
        for i in range(root.childCount()):
            item = root.child(i)
            snapshot_id = item.data(0, Qt.ItemDataRole.UserRole)
            
            if snapshot_id in self.snapshots:
                snapshot_data = self.snapshots[snapshot_id]
                
                # Check if item matches filter panel filters
                should_show = self.filter_panel.matches_filters(snapshot_data)
                
                # Apply patching filter if enabled
                if should_show and patching_only:
                    snapshot_name = snapshot_data.get('name', '').lower()
                    should_show = 'patch' in snapshot_name
                
                item.setHidden(not should_show)
                if should_show:
                    visible_count += 1
                
                # Re-apply age-based highlighting when threshold changes
                self.update_age_highlighting(item, snapshot_data, age_threshold)
        
        # Update counter to show filtered results
        total_count = self.tree.topLevelItemCount()
        if visible_count == total_count:
            self.counter_label.setText(f"Snapshots: {total_count}")
        else:
            self.counter_label.setText(f"Snapshots: {visible_count} of {total_count} shown")
    
    def update_age_highlighting(self, item, snapshot_data, age_threshold):
        """
        Update age-based highlighting for a tree item.
        
        Args:
            item: QTreeWidgetItem to update
            snapshot_data: Dictionary containing snapshot information
            age_threshold: Age threshold in business days
        """
        try:
            created_date = datetime.strptime(snapshot_data['created'], '%Y-%m-%d %H:%M')
            current_date = datetime.now()
            
            # Get day type from filter panel  
            day_type = self.filter_panel.get_day_type()
            
            # Calculate days based on selected type
            if day_type == "business days":
                days_old = self.get_business_days(created_date, current_date)
            else:  # calendar days
                days_old = self.get_calendar_days(created_date, current_date)
            
            # Check if snapshot is part of a chain (already has different highlighting)
            is_in_chain = snapshot_data.get('has_children', False) or snapshot_data.get('is_child', False)
            
            if days_old > age_threshold and not is_in_chain:
                # Apply age highlighting
                background_color = QColor(255, 255, 200)  # Light yellow
                text_color = QColor(139, 69, 19)  # Saddle brown
                
                for column in range(8):
                    item.setBackground(column, QBrush(background_color))
                    item.setForeground(column, QBrush(text_color))
                
                age_text = f"Snapshot is {days_old} {day_type} old (threshold: {age_threshold} {day_type})"
                item.setToolTip(0, age_text)
            elif not is_in_chain:
                # Remove age highlighting (but preserve chain highlighting if applicable)
                for column in range(8):
                    item.setBackground(column, QBrush())  # Clear background
                    item.setForeground(column, QBrush())  # Clear foreground
                
                # Clear age-related tooltip
                item.setToolTip(0, "")
                
        except (ValueError, KeyError):
            # If date parsing fails, don't apply highlighting
            pass
    
    def update_snapshot_counter(self):
        """
        Update the snapshot counter label.
        """
        self.counter_label.setText(f"Snapshots: {self.tree.topLevelItemCount()}")
    
    def clear_filters_on_refresh(self):
        """
        Reset all filters to defaults when snapshots are refreshed.
        """
        self.filter_panel.reset_all_filters_to_defaults()
        self.update_old_snapshots_label()
    
    def save_patch_filter_state(self):
        """
        Save the patch filter checkbox state to settings.
        """
        settings = QSettings()
        settings.setValue("PatchFilterEnabled", self.patch_filter_checkbox.isChecked())
    
    def sync_patch_filter_to_panel(self):
        """
        Sync the main patch filter checkbox state to the filter panel.
        """
        self.filter_panel.set_patching_filter(self.patch_filter_checkbox.isChecked())
    
    def sync_patch_filter_from_panel(self):
        """
        Sync the filter panel's patch filter state back to the main checkbox.
        """
        current_main_state = self.patch_filter_checkbox.isChecked()
        panel_state = self.filter_panel.get_patching_filter()
        
        if current_main_state != panel_state:
            # Temporarily disconnect to avoid infinite loop
            self.patch_filter_checkbox.stateChanged.disconnect(self.sync_patch_filter_to_panel)
            self.patch_filter_checkbox.setChecked(panel_state)
            self.save_patch_filter_state()  # Save the new state
            self.patch_filter_checkbox.stateChanged.connect(self.sync_patch_filter_to_panel)
    
    def update_old_snapshots_label(self):
        """
        Update the old snapshots color legend label with current filter settings.
        """
        if hasattr(self, 'old_snapshots_layout') and hasattr(self, 'filter_panel'):
            age_threshold = self.filter_panel.get_age_threshold()
            day_type = self.filter_panel.get_day_type()
            
            # Find the label widget in the layout and update its text
            for i in range(self.old_snapshots_layout.count()):
                item = self.old_snapshots_layout.itemAt(i)
                if item and item.widget() and isinstance(item.widget(), QLabel):
                    widget = item.widget()
                    # Skip the color box (first item) and update the text label
                    if widget.text() and "Snapshots" in widget.text():
                        widget.setText(f"Snapshots > {age_threshold} {day_type}")
                        break
    
    def show_chain_snapshot_help(self):
        """
        Show help dialog explaining chain snapshots.
        """
        QMessageBox.information(
            self,
            "About Chain Snapshots",
            "<h3>What are Chain Snapshots?</h3>"
            "<p>Chain snapshots are part of a snapshot hierarchy where one snapshot depends on another. "
            "In VMware, when you create multiple snapshots, they form a chain where each snapshot stores "
            "only the changes made since the previous snapshot.</p>"
            
            "<h3>Why can't I delete them here?</h3>"
            "<p>Chain snapshots cannot be safely deleted through this application because:</p>"
            "<ul>"
            "<li><b>Data Dependencies:</b> Child snapshots depend on their parent snapshots</li>"
            "<li><b>Risk of Corruption:</b> Deleting a parent breaks all child snapshots</li>"
            "<li><b>Complex Consolidation:</b> VMware must carefully merge disk changes</li>"
            "</ul>"
            
            "<h3>How to manage them?</h3>"
            "<p>Use <b>vSphere Client</b> to properly delete chain snapshots. VMware will handle "
            "the complex disk consolidation process to ensure your VM data remains intact.</p>"
            
            "<p><i>Tip: Independent snapshots (not grayed out) can be safely deleted using pySnap.</i></p>"
        )

class ConfigManager:
    def __init__(self):
        self.config_file = os.path.join(os.path.expanduser("~"), ".vmware_snapshot_viewer.json")
        self.keyring_service = "vmware_snapshot_manager"
    
    def save_servers(self, servers):
        """Save server configurations (without passwords)"""
        try:
            config = {
                'servers': [{
                    'hostname': server,
                    'username': username
                } for server, username in servers.items()]
            }
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            print(f"Failed to save config: {e}")
    
    def save_password(self, hostname, username, password):
        """Save password securely in system keyring"""
        try:
            key = f"{hostname}:{username}"
            keyring.set_password(self.keyring_service, key, password)
            return True
        except Exception as e:
            print(f"Failed to save password: {e}")
            return False
    
    def get_password(self, hostname, username):
        """Get password from system keyring"""
        try:
            key = f"{hostname}:{username}"
            return keyring.get_password(self.keyring_service, key)
        except Exception as e:
            print(f"Failed to get password: {e}")
            return None

    def load_servers(self):
        """Load saved server configurations"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    return {
                        server['hostname']: server['username']
                        for server in config.get('servers', [])
                    }
        except Exception as e:
            print(f"Failed to load config: {e}")
        return {}

class CreateSnapshotsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Snapshots")
        self.setModal(True)
        self.resize(500, 400)
        
        # Load last window position
        settings = QSettings()
        self.saved_geometry = settings.value("CreateSnapshotsDialogGeometry")
        
        layout = QVBoxLayout(self)
        
        # Instructions
        instructions = QLabel("Enter server names (one per line):")
        layout.addWidget(instructions)
        
        # Text area for server names with plain text settings
        self.server_list = CleanTextEdit()
        self.server_list.setAcceptRichText(False)
        self.server_list.setPlaceholderText("server1\nserver2\nserver3")
        
        # Force plain text paste
        self.server_list.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.server_list.setAutoFormatting(QTextEdit.AutoFormattingFlag.AutoNone)
        
        # Set a monospace font for better readability
        font = self.server_list.font()
        font.setFamily("Monospace")
        self.server_list.setFont(font)
        
        layout.addWidget(self.server_list)
        
        # Description field
        desc_layout = QHBoxLayout()
        desc_label = QLabel("Snapshot Description:")
        self.desc_input = QLineEdit("Monthly OS Patching")
        desc_layout.addWidget(desc_label)
        desc_layout.addWidget(self.desc_input)
        layout.addLayout(desc_layout)
        
        # Memory snapshot option with warning
        self.memory_check = QCheckBox("Include memory in snapshot (Not Recommended)")
        self.memory_check.setChecked(False)
        layout.addWidget(self.memory_check)
        
        # Warning label for memory option
        memory_warning = QLabel(
            "⚠️ Warning: Including memory will significantly increase snapshot size and\n"
            "creation time. This may impact system performance and storage usage.\n"
            "Only use this option if specifically required."
        )
        memory_warning.setStyleSheet("color: #FF6B6B; font-style: italic;")  # Red warning text
        layout.addWidget(memory_warning)
        
        # Buttons
        button_box = QHBoxLayout()
        create_btn = QPushButton("Create Snapshots")
        create_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        
        button_box.addWidget(create_btn)
        button_box.addWidget(cancel_btn)
        layout.addLayout(button_box)

    def showEvent(self, event):
        """Handle window show event"""
        super().showEvent(event)
        
        # Apply saved position or center the window
        if self.saved_geometry:
            self.restoreGeometry(self.saved_geometry)
        else:
            # Center on screen
            screen = QApplication.primaryScreen().geometry()
            window_size = self.geometry()
            x = (screen.width() - window_size.width()) // 2
            y = (screen.height() - window_size.height()) // 2
            self.move(x, y)

    def get_data(self):
        servers = [s.strip() for s in self.server_list.toPlainText().split('\n') if s.strip()]
        return {
            'servers': servers,
            'description': self.desc_input.text(),
            'memory': self.memory_check.isChecked()
        }

    def closeEvent(self, event):
        """Save window position when closing"""
        settings = QSettings()
        settings.setValue("CreateSnapshotsDialogGeometry", self.saveGeometry())
        super().closeEvent(event)

class CleanTextEdit(QTextEdit):
    def insertFromMimeData(self, source):
        """Override paste behavior to clean up text"""
        if source.hasText():
            # Get text and clean it
            text = source.text()
            
            # Split into lines, strip whitespace, and filter out empty lines
            lines = [line.strip() for line in text.splitlines()]
            clean_lines = [line for line in lines if line]
            
            # Join back together and set as plain text
            clean_text = '\n'.join(clean_lines)
            
            # Create new mime data with clean text
            clean_mime = QMimeData()
            clean_mime.setText(clean_text)
            
            # Call parent method with clean data
            super().insertFromMimeData(clean_mime)
        else:
            super().insertFromMimeData(source)

class AutoConnectWorker(QThread):
    """Worker thread for auto-connecting to saved vCenters"""
    progress = pyqtSignal(str)  # status message
    connection_made = pyqtSignal(str, object, dict)  # hostname, service_instance, credentials
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, saved_servers, config_manager):
        super().__init__()
        self.saved_servers = saved_servers
        self.config_manager = config_manager

    def run(self):
        try:
            # Set socket timeout for all connections in this thread
            socket.setdefaulttimeout(10.0)  # Increased to 10 seconds
            
            servers = list(self.saved_servers.items())
            total = len(servers)
            connected = 0
            
            for hostname, username in servers:
                password = self.config_manager.get_password(hostname, username)
                if password:
                    try:
                        connected += 1
                        self.progress.emit(f"Auto-connecting to {hostname}... ({connected}/{total})")
                        
                        # Create SSL context that ignores verification
                        context = ssl.create_default_context()
                        context.check_hostname = False
                        context.verify_mode = ssl.CERT_NONE
                        
                        # Disable SSL verification warnings
                        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                        
                        si = SmartConnect(
                            host=hostname,
                            user=username,
                            pwd=password,
                            sslContext=context,
                            disableSslCertValidation=True
                        )
                        
                        if si:
                            credentials = {'username': username, 'password': password}
                            self.connection_made.emit(hostname, si, credentials)
                        else:
                            self.error.emit(f"Failed to connect to {hostname}: No service instance returned")
                    except socket.timeout:
                        self.error.emit(f"Connection to {hostname} timed out after 10 seconds")
                        # Continue with next server
                    except socket.gaierror as e:
                        self.error.emit(f"Cannot resolve hostname {hostname}: {str(e)}")
                        # Continue with next server
                    except ConnectionRefusedError as e:
                        self.error.emit(f"Connection refused by {hostname}: {str(e)}")
                        # Continue with next server
                    except Exception as e:
                        # Log but don't crash - continue with next server
                        self.error.emit(f"Failed to auto-connect to {hostname}: {type(e).__name__}: {str(e)}")
                        # Continue with next server
            
            self.finished.emit()
        except Exception as e:
            self.error.emit(f"Auto-connect error: {str(e)}")
        finally:
            # Reset socket timeout to default
            socket.setdefaulttimeout(None)

class SnapshotCreateWorker(QThread):
    progress = pyqtSignal(int, int, str)  # completed, total, message
    finished = pyqtSignal()
    error = pyqtSignal(str)
    snapshot_created = pyqtSignal(dict)  # Changed from str to dict to include snapshot details for caching

    def __init__(self, vcenter_connections, servers, description, memory=False, vcenter_username=None):
        super().__init__()
        self.vcenter_connections = vcenter_connections
        self.servers = servers
        self.description = description
        self.memory = memory
        self.vcenter_username = vcenter_username or getpass.getuser()  # Fallback to system user
        self.batch_size = 5  # Process 5 servers per vCenter at a time

    def run(self):
        total = len(self.servers)
        completed = 0
        failed = []
        
        # Show initial progress
        ProgressTracker.emit_progress(
            self.progress, 0, total,
            "Locating", "VMs"
        )
        
        # Group servers by vCenter
        servers_by_vcenter = {}
        for i, server in enumerate(self.servers, 1):
            # Update progress during VM discovery
            ProgressTracker.emit_progress(
                self.progress, i-1, total,
                "Finding", f"{server}"
            )
            
            # Find which vCenter the VM belongs to
            found = False
            for si in self.vcenter_connections.values():
                vm = self.find_vm_in_vcenter(si, server)
                if vm:
                    vcenter = si._stub.host
                    if vcenter not in servers_by_vcenter:
                        servers_by_vcenter[vcenter] = []
                    servers_by_vcenter[vcenter].append((vm, server))
                    found = True
                    break
            if not found:
                failed.append(f"Server not found: {server}")

        if not servers_by_vcenter:
            self.error.emit("No VMs were found in any connected vCenter")
            self.finished.emit()
            return

        # Show how many VMs were found
        found_count = sum(len(servers) for servers in servers_by_vcenter.values())
        ProgressTracker.emit_progress(
            self.progress, 0, total,
            "Creating", f"Found {found_count}"
        )

        # Process each vCenter's servers in batches
        active_tasks = {}  # {task: (server_name, vcenter_name)}
        
        for vcenter, server_list in servers_by_vcenter.items():
            ProgressTracker.emit_progress(
                self.progress, completed, total,
                "Creating", f"{vcenter}"
            )
            
            for i in range(0, len(server_list), self.batch_size):
                batch = server_list[i:i + self.batch_size]
                batch_servers = [s[1] for s in batch]
                ProgressTracker.emit_progress(
                    self.progress, completed, total,
                    "Batch", f"{len(batch_servers)} VMs"
                )
                
                # Start snapshot creation for batch
                for vm, server in batch:
                    try:
                        # Add creator information to description using vCenter username
                        description_with_creator = f"{self.description} (Created by: {self.vcenter_username})"
                        
                        task = vm.CreateSnapshot_Task(
                            name=f"Monthly OS Patching",
                            description=description_with_creator,
                            memory=self.memory,
                            quiesce=False
                        )
                        active_tasks[task] = (server, vcenter)
                    except Exception as e:
                        failed.append(f"Error creating snapshot for {server}: {str(e)}")

                # Monitor tasks
                while active_tasks:
                    for task in list(active_tasks.keys()):
                        server, vcenter = active_tasks[task]
                        try:
                            if task.info.state == vim.TaskInfo.State.success:
                                completed += 1
                                # Get the snapshot we just created
                                snapshot_obj = None
                                if vm.snapshot:
                                    # Find the snapshot that was just created
                                    for snapshot in self.get_snapshots(vm.snapshot.rootSnapshotList):
                                        if snapshot.name == "Monthly OS Patching" and format_vmware_time(snapshot.createTime)[:10] == datetime.now().strftime('%Y-%m-%d'):
                                            snapshot_obj = snapshot
                                            break
                                
                                if snapshot_obj:
                                    # Get creator information from description
                                    # VMware snapshots don't have a built-in createdBy property
                                    created_by = self.extract_creator_from_description(snapshot_obj.description)
                                    
                                    # Emit snapshot details in the same format as SnapshotFetchWorker
                                    # This enables caching by directly adding to the tree without refetching
                                    self.snapshot_created.emit({
                                        'vm_name': vm.name,
                                        'vcenter': vcenter,
                                        'name': snapshot_obj.name,
                                        'created': format_vmware_time(snapshot_obj.createTime),
                                        'created_by': created_by,
                                        'description': snapshot_obj.description or '',
                                        'snapshot': snapshot_obj,
                                        'vm': vm,
                                        'has_children': bool(snapshot_obj.childSnapshotList),
                                        'is_child': hasattr(snapshot_obj, 'parent') and snapshot_obj.parent is not None
                                    })
                                else:
                                    # If we can't find the snapshot object, just emit the server name
                                    # This ensures backward compatibility
                                    self.snapshot_created.emit({'vm_name': server})
                                
                                ProgressTracker.emit_progress(
                                    self.progress, completed, total,
                                    "Created", f"{(completed/total)*100:.1f}%"
                                )
                                del active_tasks[task]
                            elif task.info.state == vim.TaskInfo.State.error:
                                failed.append(f"Failed: {server}: {task.info.error.msg}")
                                del active_tasks[task]
                            else:
                                # Show individual task progress
                                task_progress = task.info.progress or 0
                                active_count = len(active_tasks)
                                ProgressTracker.emit_progress(
                                    self.progress, completed, total,
                                    "Working", f"{server} ({task_progress}%)"
                                )
                        except Exception as e:
                            failed.append(f"Error monitoring {server}: {str(e)}")
                            del active_tasks[task]
                    time.sleep(0.5)

        # Final status
        if failed:
            self.error.emit("\n".join(failed))
        ProgressTracker.emit_progress(
            self.progress, completed, total,
            "Complete", f"{completed} done" + (f", {len(failed)} failed" if failed else "")
        )
        self.finished.emit()

    def find_vm_in_vcenter(self, si, name):
        """Find VM by name in a specific vCenter"""
        content = si.RetrieveContent()
        container = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.VirtualMachine], True
        )
        for vm in container.view:
            if vm.name.lower() == name.lower():
                return vm
        container.Destroy()
        return None

    def find_vm(self, name):
        """Find VM by name across all connected vCenters"""
        for si in self.vcenter_connections.values():
            vm = self.find_vm_in_vcenter(si, name)
            if vm:
                return vm
        return None
        
    def get_snapshots(self, snapshots):
        """Helper method to traverse snapshot tree"""
        result = []
        for snapshot in snapshots:
            result.append(snapshot)
            result.extend(self.get_snapshots(snapshot.childSnapshotList))
        return result
    
    def extract_creator_from_description(self, description):
        """
        Extract creator information from snapshot description.
        
        VMware snapshots don't have a built-in createdBy property,
        so we look for creator information in the description field.
        
        Args:
            description (str): The snapshot description
            
        Returns:
            str: The username who created the snapshot, or 'Unknown'
        """
        if not description:
            return 'Unknown'
        
        import re
        
        # Look for patterns like "Created by: username" or "(Created by: username)"
        patterns = [
            r'Created by:\s*(\w+)',
            r'\(Created by:\s*(\w+)\)',
            r'User:\s*(\w+)',
            r'By:\s*(\w+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, description, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return 'Unknown'


def handle_exception(exc_type, exc_value, exc_traceback):
    """Global exception handler"""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    
    # Log the exception
    logger = logging.getLogger('pySnap')
    logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
    
    # Show simple error dialog
    from PyQt6.QtWidgets import QMessageBox
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Icon.Critical)
    msg.setWindowTitle("Application Error")
    msg.setText("An unexpected error occurred. Check the log file ~/pysnap.log for details.")
    msg.exec()

if __name__ == "__main__":
    try:
        # Set up global exception handler
        sys.excepthook = handle_exception
        
        # Fix for macOS focus issues
        # os.environ['QT_MAC_WANTS_LAYER'] = '1'
        
        app = QApplication(sys.argv)
        app.setApplicationName("pySnap")
        app.setApplicationDisplayName("pySnap - VMware Snapshot Manager")
        app.setOrganizationName("LAUSD")
        app.setOrganizationDomain("lausd.net")
        
        # Set application icon
        icon_path = os.path.join(os.path.dirname(__file__), 'icons', 'app_icon.png')
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
        
        window = SnapshotManagerWindow()
        window.show()
        
        sys.exit(app.exec())
        
    except Exception as e:
        # Fallback error handling
        print(f"Critical error during startup: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)