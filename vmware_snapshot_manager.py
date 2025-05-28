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
import os
import json
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
import urllib3
import time
from PyQt6.QtGui import QColor, QBrush, QIcon
import keyring
from PyQt6.QtCore import QSettings

# Built by Christian Salas

class SnapshotFetchWorker(QThread):
    """Worker thread for fetching snapshots"""
    finished = pyqtSignal()
    progress = pyqtSignal(str)
    snapshot_found = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, vcenter_connections):
        super().__init__()
        self.vcenter_connections = vcenter_connections

    def run(self):
        try:
            for hostname, si in self.vcenter_connections.items():
                self.progress.emit(f"Fetching from {hostname}...")
                content = si.RetrieveContent()
                container = content.viewManager.CreateContainerView(
                    content.rootFolder, [vim.VirtualMachine], True
                )
                
                for vm in container.view:
                    if vm.snapshot:
                        for snapshot in self.get_snapshots(vm.snapshot.rootSnapshotList):
                            if 'patch' in snapshot.name.lower():
                                self.snapshot_found.emit({
                                    'vm_name': vm.name,
                                    'vcenter': hostname,
                                    'name': snapshot.name,
                                    'created': snapshot.createTime.strftime('%Y-%m-%d %H:%M'),
                                    'snapshot': snapshot,
                                    'vm': vm,
                                    'has_children': bool(snapshot.childSnapshotList),
                                    'is_child': hasattr(snapshot, 'parent') and snapshot.parent is not None
                                })
                container.Destroy()
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

    def get_snapshots(self, snapshots):
        result = []
        for snapshot in snapshots:
            result.append(snapshot)
            result.extend(self.get_snapshots(snapshot.childSnapshotList))
        return result

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
    progress = pyqtSignal(str)
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
                self.progress.emit(f"Starting deletion of {data['name']} from {data['vm_name']}")
                
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
                self.progress.emit(f"Deleting snapshots... {overall_progress:.0f}%")
            
            # Small delay before next check
            time.sleep(0.5)
        
        self.progress.emit("Deletion complete")
        self.finished.emit()

class SnapshotManagerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VMware Patching Snapshot Manager")
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
        self.logger = logging.getLogger('SnapshotManager')
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
        
        self.clear_conn_btn = QPushButton("Clear Connections")
        self.clear_conn_btn.clicked.connect(self.clear_connections)
        self.clear_conn_btn.setEnabled(False)
        
        self.conn_label = QLabel("No active connections")
        
        conn_layout.addWidget(self.add_conn_btn)
        conn_layout.addWidget(self.clear_conn_btn)
        conn_layout.addWidget(self.conn_label)
        conn_layout.addStretch()
        
        # Tree widget for snapshots
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Select", "VM Name", "vCenter", "Snapshot Name", "Created", "Snapshot Type"])
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
        def create_color_box(color, text):
            box_layout = QHBoxLayout()
            color_box = QLabel()
            color_box.setFixedSize(16, 16)
            color_box.setStyleSheet(f"background-color: {color}; border: 1px solid #666;")
            label = QLabel(text)
            box_layout.addWidget(color_box)
            box_layout.addWidget(label)
            box_layout.addStretch()
            return box_layout

        # Add color legends
        highlight_layout.addLayout(create_color_box("#CCCCCC", "Child Snapshots"))  # Gray for child snapshots
        highlight_layout.addLayout(create_color_box("#FFFF99", "Snapshots > 3 Business Days Old"))  # Yellow for old snapshots
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
        self.progress_bar.setMaximumWidth(200)  # Limit width
        self.progress_bar.hide()  # Hidden by default
        self.counter_label = QLabel("Snapshots: 0")
        
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.progress_bar)
        status_layout.addStretch()
        status_layout.addWidget(self.counter_label)
        
        # Add all sections to main layout
        main_layout.addWidget(conn_frame)
        main_layout.addWidget(self.tree)
        main_layout.addWidget(highlight_frame)
        main_layout.addWidget(button_frame)
        main_layout.addWidget(status_frame)

        # Add column widths
        self.tree.setColumnWidth(0, 50)   # Checkbox column
        self.tree.setColumnWidth(1, 200)  # VM Name
        self.tree.setColumnWidth(2, 200)  # vCenter
        self.tree.setColumnWidth(3, 200)  # Snapshot Name
        self.tree.setColumnWidth(4, 150)  # Created
        self.tree.setColumnWidth(5, 150)  # Snapshot Type column - increased width for new name

        # After loading saved_servers
        self.check_auto_connect()

        # Add settings menu
        menubar = self.menuBar()
        settings_menu = menubar.addMenu('Settings')
        
        auto_connect_action = settings_menu.addAction('Auto-Connect Settings')
        auto_connect_action.triggered.connect(self.show_auto_connect_settings)

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
        log_file = os.path.join(os.path.expanduser("~"), "snapshot_manager.log")
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
        logger = logging.getLogger('SnapshotManager')
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
                # Create SSL context that ignores verification
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                
                # Disable SSL verification warnings
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                
                si = SmartConnect(
                    host=data['hostname'],
                    user=data['username'],
                    pwd=data['password'],
                    sslContext=context,
                    disableSslCertValidation=True
                )
                
                if si:
                    self.vcenter_connections[data['hostname']] = si
                    self.active_credentials[data['hostname']] = {
                        'username': data['username'],
                        'password': data['password']
                    }
                    if data['save']:
                        self.saved_servers[data['hostname']] = data['username']
                        self.config_manager.save_servers(self.saved_servers)
                        self.config_manager.save_password(
                            data['hostname'],
                            data['username'],
                            data['password']
                        )
                    self.update_connection_status()
                    
            except Exception as e:
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
        self.fetch_button.setEnabled(False)
        self.delete_button.setText("Delete Selected")  # Reset delete button text
        self.status_label.setText("Fetching snapshots...")
        
        self.fetch_worker = SnapshotFetchWorker(self.vcenter_connections)
        self.fetch_worker.progress.connect(self.status_label.setText)
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
            
            for column in range(6):
                item.setBackground(column, QBrush(warning_color))
                item.setForeground(column, QBrush(warning_text))
            
            # Add warning tooltip
            chain_status = []
            if data['has_children']:
                chain_status.append("Has child snapshots")
            if data['is_child']:
                chain_status.append("Is a child snapshot")
            
            warning_text = "Cannot delete: " + " and ".join(chain_status)
            warning_text += "\nPlease use vSphere Client to manage snapshot chains"
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
        item.setText(5, chain_status)
        
        # Check if snapshot is older than 3 business days
        created_date = datetime.strptime(data['created'], '%Y-%m-%d %H:%M')
        current_date = datetime.now()
        
        # Calculate business days between dates
        business_days = self.get_business_days(created_date, current_date)
        
        if business_days > 3:
            # Highlight old snapshots with yellow colors
            background_color = QColor(255, 255, 200)  # Light yellow
            text_color = QColor(139, 69, 19)  # Saddle brown (dark brown)
            
            for column in range(6):
                item.setBackground(column, QBrush(background_color))
                item.setForeground(column, QBrush(text_color))
            
            # Add tooltip with age information
            age_text = f"Snapshot is {business_days} business days old"
            item.setToolTip(0, age_text)
        
        # Generate a unique ID for the snapshot
        snapshot_id = f"{data['vcenter']}_{data['vm_name']}_{data['name']}"
        
        # Store the ID in the item's data
        item.setData(0, Qt.ItemDataRole.UserRole, snapshot_id)
        
        # Store snapshot data using the ID
        self.snapshots[snapshot_id] = data
        
        # Update counter
        self.counter_label.setText(f"Snapshots: {self.tree.topLevelItemCount()}")

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

    def on_fetch_error(self, error_msg):
        """Handle fetch errors"""
        QMessageBox.warning(self, "Error", f"Failed to fetch snapshots: {error_msg}")
        self.fetch_button.setEnabled(True)

    def on_fetch_complete(self):
        """Handle fetch completion"""
        self.status_label.setText("Ready")
        self.fetch_button.setEnabled(True)
        self.delete_button.setEnabled(True)

    def start_delete(self, selected_items):
        """Start deletion process"""
        self.fetch_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        
        self.delete_worker = SnapshotDeleteWorker(selected_items)
        self.delete_worker.progress.connect(self.status_label.setText)
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
        self.counter_label.setText(f"Snapshots: {self.tree.topLevelItemCount()}")
        
        # Reset delete button text after deletion
        self.delete_button.setText("Delete Selected")

    def on_delete_complete(self):
        """Handle deletion completion"""
        self.status_label.setText("Ready")
        self.fetch_button.setEnabled(True)
        self.delete_button.setEnabled(True)

    def check_connections(self):
        """Check all connections and reconnect if needed"""
        for hostname, si in list(self.vcenter_connections.items()):
            try:
                # Test connection by making a simple API call
                si.CurrentTime()
            except Exception as e:
                self.logger.warning(f"Connection to {hostname} lost: {str(e)}")
                
                # Try to reconnect if we have credentials
                if hostname in self.active_credentials:
                    self.status_label.setText(f"Reconnecting to {hostname}...")
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
                            self.status_label.setText("Ready")
                        else:
                            self.logger.error(f"Failed to reconnect to {hostname}")
                            self.status_label.setText("Ready")
                            
                    except Exception as reconnect_error:
                        self.logger.error(f"Failed to reconnect to {hostname}: {str(reconnect_error)}")
                        self.status_label.setText("Ready")
                        # Remove failed connection
                        self.vcenter_connections.pop(hostname, None)
                        self.active_credentials.pop(hostname, None)
                else:
                    # No credentials available, remove the connection
                    self.vcenter_connections.pop(hostname, None)
        
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
        
        self.create_worker = SnapshotCreateWorker(
            self.vcenter_connections, 
            servers, 
            description,
            memory
        )
        self.create_worker.progress.connect(
            lambda completed, total, msg: self.update_progress(completed, total, msg)
        )
        self.create_worker.error.connect(lambda msg: QMessageBox.warning(self, "Errors Occurred", msg))
        self.create_worker.snapshot_created.connect(self.handle_created_snapshot)
        self.create_worker.finished.connect(self.on_create_complete)
        self.create_worker.start()
        
    def handle_created_snapshot(self, snapshot_data):
        """Handle newly created snapshots by adding them directly to the tree"""
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
        """Handle completion of snapshot creation"""
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
        """Update progress bar and status"""
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
        """Reset progress bar and status"""
        self.progress_bar.hide()
        self.progress_bar.setValue(0)
        self.status_label.setText("Ready")

    def check_auto_connect(self):
        """Check and handle auto-connect settings"""
        settings = QSettings()
        
        # Check if this is first run or if we should ask
        first_run = settings.value("FirstRun", True, type=bool)
        auto_connect = settings.value("AutoConnect", None)
        
        if first_run or auto_connect is None:
            dialog = AutoConnectDialog(self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                auto_connect = dialog.auto_connect.isChecked()
                if dialog.dont_ask.isChecked():
                    settings.setValue("AutoConnect", auto_connect)
                settings.setValue("FirstRun", False)
        
        # Perform auto-connect if enabled
        if auto_connect:
            self.status_label.setText("Auto-connecting to saved vCenters...")
            QTimer.singleShot(0, self.auto_connect_to_saved)

    def auto_connect_to_saved(self):
        """Automatically connect to all saved vCenters"""
        for hostname, username in self.saved_servers.items():
            password = self.config_manager.get_password(hostname, username)
            if password:
                try:
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
                        self.vcenter_connections[hostname] = si
                        self.active_credentials[hostname] = {
                            'username': username,
                            'password': password
                        }
                        self.logger.info(f"Auto-connected to {hostname}")
                except Exception as e:
                    self.logger.error(f"Failed to auto-connect to {hostname}: {str(e)}")
        
        # Update UI after all connection attempts
        self.update_connection_status()
        self.status_label.setText("Ready")

    def show_auto_connect_settings(self):
        """Show dialog to modify auto-connect settings"""
        settings = QSettings()
        current_setting = settings.value("AutoConnect", False, type=bool)
        
        dialog = AutoConnectDialog(self)
        dialog.auto_connect.setChecked(current_setting)
        dialog.dont_ask.hide()  # Hide "don't ask again" when accessed from menu
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            settings.setValue("AutoConnect", dialog.auto_connect.isChecked())

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
        self.desc_input = QLineEdit("Monthly Patching")
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

class SnapshotCreateWorker(QThread):
    progress = pyqtSignal(int, int, str)  # completed, total, message
    finished = pyqtSignal()
    error = pyqtSignal(str)
    snapshot_created = pyqtSignal(dict)  # Changed from str to dict to include snapshot details

    def __init__(self, vcenter_connections, servers, description, memory=False):
        super().__init__()
        self.vcenter_connections = vcenter_connections
        self.servers = servers
        self.description = description
        self.memory = memory
        self.batch_size = 5  # Process 5 servers per vCenter at a time

    def run(self):
        total = len(self.servers)
        completed = 0
        failed = []
        
        # Show initial progress
        self.progress.emit(0, total, "Locating VMs across vCenters...")
        
        # Group servers by vCenter
        servers_by_vcenter = {}
        for i, server in enumerate(self.servers, 1):
            # Update progress during VM discovery
            self.progress.emit(0, total, f"Locating VM: {server} ({i}/{total})")
            
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
        self.progress.emit(0, total, f"Found {found_count} VMs. Starting snapshot creation...")

        # Process each vCenter's servers in batches
        active_tasks = {}  # {task: (server_name, vcenter_name)}
        
        for vcenter, server_list in servers_by_vcenter.items():
            self.progress.emit(completed, total, f"Creating snapshots on {vcenter}")
            
            for i in range(0, len(server_list), self.batch_size):
                batch = server_list[i:i + self.batch_size]
                batch_servers = [s[1] for s in batch]
                self.progress.emit(completed, total, 
                    f"Starting batch: {', '.join(batch_servers)}")
                
                # Start snapshot creation for batch
                for vm, server in batch:
                    try:
                        task = vm.CreateSnapshot_Task(
                            name=f"Monthly Patching",
                            description=self.description,
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
                                        if snapshot.name == "Monthly Patching" and snapshot.createTime.strftime('%Y-%m-%d') == datetime.now().strftime('%Y-%m-%d'):
                                            snapshot_obj = snapshot
                                            break
                                
                                if snapshot_obj:
                                    # Emit snapshot details in the same format as SnapshotFetchWorker
                                    self.snapshot_created.emit({
                                        'vm_name': vm.name,
                                        'vcenter': vcenter,
                                        'name': snapshot_obj.name,
                                        'created': snapshot_obj.createTime.strftime('%Y-%m-%d %H:%M'),
                                        'snapshot': snapshot_obj,
                                        'vm': vm,
                                        'has_children': bool(snapshot_obj.childSnapshotList),
                                        'is_child': hasattr(snapshot_obj, 'parent') and snapshot_obj.parent is not None
                                    })
                                else:
                                    # If we can't find the snapshot object, just emit the server name
                                    # This ensures backward compatibility
                                    self.snapshot_created.emit({'vm_name': server})
                                
                                self.progress.emit(completed, total, 
                                    f"Progress: {completed}/{total} ({(completed/total)*100:.1f}%)")
                                del active_tasks[task]
                            elif task.info.state == vim.TaskInfo.State.error:
                                failed.append(f"Failed: {server}: {task.info.error.msg}")
                                del active_tasks[task]
                            else:
                                # Show individual task progress
                                task_progress = task.info.progress or 0
                                active_count = len(active_tasks)
                                self.progress.emit(completed, total,
                                    f"Progress: {completed}/{total} - Active tasks: {active_count} - Current: {server} ({task_progress}%)")
                        except Exception as e:
                            failed.append(f"Error monitoring {server}: {str(e)}")
                            del active_tasks[task]
                    time.sleep(0.5)

        # Final status
        if failed:
            self.error.emit("\n".join(failed))
        self.progress.emit(completed, total, 
            f"Completed: {completed}/{total} successful" + 
            (f" ({len(failed)} failed)" if failed else ""))
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

class AutoConnectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Auto-Connect Settings")
        self.setModal(True)
        
        layout = QVBoxLayout(self)
        
        # Message
        msg = QLabel(
            "Would you like to automatically connect to saved vCenters when the application starts?\n"
            "This will use your saved credentials from the system keychain."
        )
        msg.setWordWrap(True)
        layout.addWidget(msg)
        
        # Checkbox
        self.auto_connect = QCheckBox("Auto-connect to saved vCenters on startup")
        self.auto_connect.setChecked(True)
        layout.addWidget(self.auto_connect)
        
        # Don't ask again checkbox
        self.dont_ask = QCheckBox("Remember my choice and don't ask again")
        self.dont_ask.setChecked(True)
        layout.addWidget(self.dont_ask)
        
        # Buttons
        button_box = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        
        button_box.addWidget(ok_btn)
        button_box.addWidget(cancel_btn)
        layout.addLayout(button_box)

if __name__ == "__main__":
    # Fix for macOS focus issues
    # os.environ['QT_MAC_WANTS_LAYER'] = '1'
    
    app = QApplication(sys.argv)
    app.setApplicationName("VMware Snapshot Manager")
    app.setOrganizationName("LAUSD")
    app.setOrganizationDomain("lausd.net")
    
    # Set application icon
    icon_path = os.path.join(os.path.dirname(__file__), 'icons', 'app_icon.png')
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    window = SnapshotManagerWindow()
    window.show()
    sys.exit(app.exec())