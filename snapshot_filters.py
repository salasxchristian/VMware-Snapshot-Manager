"""
Snapshot Filtering Module

This module provides filtering capabilities for the VMware Snapshot Manager.
It includes a collapsible filter panel with various filter types for all snapshot columns.
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                            QLineEdit, QComboBox, QDateEdit, QPushButton,
                            QFrame, QGridLayout, QSizePolicy, QCheckBox, QSpinBox)
from PyQt6.QtCore import Qt, pyqtSignal, QDate
from PyQt6.QtGui import QIcon
from datetime import datetime, timedelta
import re


class SnapshotFilterPanel(QWidget):
    """
    A collapsible filter panel for snapshot filtering.
    Provides real-time filtering across all snapshot columns.
    """
    
    # Signal emitted when any filter changes
    filters_changed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_expanded = False
        self.setup_ui()
        self.connect_signals()
        
    def setup_ui(self):
        """Setup the filter panel UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)
        
        # Header with toggle button
        header_frame = QFrame()
        header_frame.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        header_layout = QHBoxLayout(header_frame)
        
        self.toggle_button = QPushButton("▶ Show Filters")
        self.toggle_button.setFixedWidth(120)
        self.toggle_button.clicked.connect(self.toggle_filters)
        
        self.clear_button = QPushButton("Clear All")
        self.clear_button.setFixedWidth(80)
        self.clear_button.clicked.connect(self.clear_all_filters)
        
        header_layout.addWidget(self.toggle_button)
        header_layout.addWidget(self.clear_button)
        header_layout.addStretch()
        
        # Filter content frame (initially hidden)
        self.filter_frame = QFrame()
        self.filter_frame.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Sunken)
        self.filter_frame.hide()
        
        filter_layout = QGridLayout(self.filter_frame)
        filter_layout.setSpacing(10)
        
        # Row 1: Text filters
        row = 0
        
        # VM Name filter
        filter_layout.addWidget(QLabel("VM Name:"), row, 0)
        self.vm_name_filter = QLineEdit()
        self.vm_name_filter.setPlaceholderText("Filter by VM name...")
        filter_layout.addWidget(self.vm_name_filter, row, 1)
        
        # Combined Snapshot/Description filter
        filter_layout.addWidget(QLabel("Name/Description:"), row, 2)
        self.snapshot_search_filter = QLineEdit()
        self.snapshot_search_filter.setPlaceholderText("Search snapshot name or description...")
        filter_layout.addWidget(self.snapshot_search_filter, row, 3)
        
        # Row 2: Dropdown filters
        row += 1
        
        # vCenter filter
        filter_layout.addWidget(QLabel("vCenter:"), row, 0)
        self.vcenter_filter = QComboBox()
        self.vcenter_filter.addItem("All vCenters")
        filter_layout.addWidget(self.vcenter_filter, row, 1)
        
        # Created By filter
        filter_layout.addWidget(QLabel("Created By:"), row, 2)
        self.created_by_filter = QComboBox()
        self.created_by_filter.addItem("All Users")
        filter_layout.addWidget(self.created_by_filter, row, 3)
        
        # Row 3: Date range and description
        row += 1
        
        # Date range filters
        filter_layout.addWidget(QLabel("Created From:"), row, 0)
        self.date_from_filter = QDateEdit()
        self.date_from_filter.setDate(QDate.currentDate().addDays(-30))  # Default: 30 days ago
        self.date_from_filter.setCalendarPopup(True)
        self.date_from_filter.setSpecialValueText("No minimum date")
        filter_layout.addWidget(self.date_from_filter, row, 1)
        
        filter_layout.addWidget(QLabel("Created To:"), row, 2)
        self.date_to_filter = QDateEdit()
        self.date_to_filter.setDate(QDate.currentDate())
        self.date_to_filter.setCalendarPopup(True)
        self.date_to_filter.setSpecialValueText("No maximum date")
        filter_layout.addWidget(self.date_to_filter, row, 3)
        
        # Row 4: Snapshot Type
        row += 1
        
        # Snapshot Type filter
        filter_layout.addWidget(QLabel("Snapshot Type:"), row, 0)
        self.snapshot_type_filter = QComboBox()
        self.snapshot_type_filter.addItem("All Types")
        self.snapshot_type_filter.addItem("Independent Snapshot")
        self.snapshot_type_filter.addItem("Child Snapshot")
        self.snapshot_type_filter.addItem("Part of Chain (Middle)")
        self.snapshot_type_filter.addItem("Has Child Snapshots (Delete Manually)")
        filter_layout.addWidget(self.snapshot_type_filter, row, 1)
        
        # Row 5: Age Filter
        row += 1
        
        # Age filter - static label
        age_label = QLabel("Highlight snapshots older than:")
        filter_layout.addWidget(age_label, row, 0)
        
        # Create horizontal layout for spinbox and day type selector
        age_control_layout = QHBoxLayout()
        age_control_widget = QWidget()
        age_control_widget.setLayout(age_control_layout)
        
        self.age_threshold_spinbox = QSpinBox()
        self.age_threshold_spinbox.setMinimum(1)
        self.age_threshold_spinbox.setMaximum(365)
        self.age_threshold_spinbox.setValue(3)  # Default to 3 business days
        self.age_threshold_spinbox.setToolTip("Snapshots older than this threshold will be highlighted in yellow")
        age_control_layout.addWidget(self.age_threshold_spinbox)
        
        self.day_type_combo = QComboBox()
        self.day_type_combo.addItem("business days")
        self.day_type_combo.addItem("calendar days")
        self.day_type_combo.setCurrentText("business days")  # Default to business days
        self.day_type_combo.setToolTip("Choose whether to count business days (Mon-Fri) or calendar days")
        age_control_layout.addWidget(self.day_type_combo)
        
        age_control_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.addWidget(age_control_widget, row, 1)
        
        # Add frames to main layout
        main_layout.addWidget(header_frame)
        main_layout.addWidget(self.filter_frame)
        
    def connect_signals(self):
        """Connect all filter controls to the signal"""
        # Text filters
        self.vm_name_filter.textChanged.connect(self.filters_changed.emit)
        self.snapshot_search_filter.textChanged.connect(self.filters_changed.emit)
        
        # Dropdown filters
        self.vcenter_filter.currentTextChanged.connect(self.filters_changed.emit)
        self.created_by_filter.currentTextChanged.connect(self.filters_changed.emit)
        self.snapshot_type_filter.currentTextChanged.connect(self.filters_changed.emit)
        
        # Date filters
        self.date_from_filter.dateChanged.connect(self.filters_changed.emit)
        self.date_to_filter.dateChanged.connect(self.filters_changed.emit)
        
        # Age threshold filter
        self.age_threshold_spinbox.valueChanged.connect(self.filters_changed.emit)
        self.day_type_combo.currentTextChanged.connect(self.filters_changed.emit)
        
    def toggle_filters(self):
        """Toggle the visibility of the filter panel"""
        if self.is_expanded:
            self.filter_frame.hide()
            self.toggle_button.setText("▶ Show Filters")
            self.is_expanded = False
        else:
            self.filter_frame.show()
            self.toggle_button.setText("▼ Hide Filters")
            self.is_expanded = True
            
    def clear_all_filters(self):
        """Clear all filter values"""
        # Clear text filters
        self.vm_name_filter.clear()
        self.snapshot_search_filter.clear()
        
        # Reset dropdown filters
        self.vcenter_filter.setCurrentIndex(0)
        self.created_by_filter.setCurrentIndex(0)
        self.snapshot_type_filter.setCurrentIndex(0)
        
        # Reset date filters to default range
        self.date_from_filter.setDate(QDate.currentDate().addDays(-30))
        self.date_to_filter.setDate(QDate.currentDate())
        
        # Reset age threshold to default
        self.age_threshold_spinbox.setValue(3)
        self.day_type_combo.setCurrentText("business days")
        
    def update_dropdown_options(self, snapshots_data):
        """
        Update dropdown filter options based on available snapshot data.
        
        Args:
            snapshots_data (dict): Dictionary of snapshot data keyed by snapshot ID
        """
        # Get unique values for dropdown filters
        vcenters = set()
        creators = set()
        
        for snapshot_data in snapshots_data.values():
            vcenters.add(snapshot_data.get('vcenter', ''))
            creators.add(snapshot_data.get('created_by', 'Unknown'))
        
        # Update vCenter dropdown
        current_vcenter = self.vcenter_filter.currentText()
        self.vcenter_filter.clear()
        self.vcenter_filter.addItem("All vCenters")
        for vcenter in sorted(vcenters):
            if vcenter:  # Only add non-empty values
                self.vcenter_filter.addItem(vcenter)
        
        # Restore selection if it still exists
        index = self.vcenter_filter.findText(current_vcenter)
        if index >= 0:
            self.vcenter_filter.setCurrentIndex(index)
        
        # Update Created By dropdown
        current_creator = self.created_by_filter.currentText()
        self.created_by_filter.clear()
        self.created_by_filter.addItem("All Users")
        for creator in sorted(creators):
            if creator and creator != 'Unknown':  # Add Unknown at the end
                self.created_by_filter.addItem(creator)
        self.created_by_filter.addItem("Unknown")
        
        # Restore selection if it still exists
        index = self.created_by_filter.findText(current_creator)
        if index >= 0:
            self.created_by_filter.setCurrentIndex(index)
    
    def get_active_filters(self):
        """
        Get current filter values as a dictionary.
        
        Returns:
            dict: Current filter values
        """
        return {
            'vm_name': self.vm_name_filter.text().strip(),
            'snapshot_search': self.snapshot_search_filter.text().strip(),
            'vcenter': self.vcenter_filter.currentText() if self.vcenter_filter.currentText() != "All vCenters" else "",
            'created_by': self.created_by_filter.currentText() if self.created_by_filter.currentText() != "All Users" else "",
            'snapshot_type': self.snapshot_type_filter.currentText() if self.snapshot_type_filter.currentText() != "All Types" else "",
            'age_threshold': self.age_threshold_spinbox.value(),
            'day_type': self.day_type_combo.currentText(),
            'date_from': self.date_from_filter.date().toPyDate(),
            'date_to': self.date_to_filter.date().toPyDate()
        }
    
    def matches_filters(self, snapshot_data):
        """
        Check if a snapshot matches all active filters.
        
        Args:
            snapshot_data (dict): Snapshot data to test
            
        Returns:
            bool: True if snapshot matches all filters
        """
        filters = self.get_active_filters()
        
        # Text filters (case-insensitive contains)
        if filters['vm_name'] and filters['vm_name'].lower() not in snapshot_data.get('vm_name', '').lower():
            return False
            
        # Combined snapshot name/description search
        if filters['snapshot_search']:
            search_term = filters['snapshot_search'].lower()
            snapshot_name = snapshot_data.get('name', '').lower()
            description = snapshot_data.get('description', '').lower()
            
            # Search term must match either snapshot name OR description
            if search_term not in snapshot_name and search_term not in description:
                return False
        
        # Dropdown filters (exact match)
        if filters['vcenter'] and filters['vcenter'] != snapshot_data.get('vcenter', ''):
            return False
            
        if filters['created_by'] and filters['created_by'] != snapshot_data.get('created_by', 'Unknown'):
            return False
        
        # Snapshot type filter
        if filters['snapshot_type']:
            # Get the snapshot type from the data
            has_children = snapshot_data.get('has_children', False)
            is_child = snapshot_data.get('is_child', False)
            
            if has_children and is_child:
                snapshot_type = "Part of Chain (Middle)"
            elif has_children:
                snapshot_type = "Has Child Snapshots (Delete Manually)"
            elif is_child:
                snapshot_type = "Child Snapshot"
            else:
                snapshot_type = "Independent Snapshot"
                
            if filters['snapshot_type'] != snapshot_type:
                return False
        
        # Date range filter
        try:
            created_str = snapshot_data.get('created', '')
            if created_str:
                # Parse the created date (format: 'YYYY-MM-DD HH:MM')
                created_date = datetime.strptime(created_str, '%Y-%m-%d %H:%M').date()
                
                if created_date < filters['date_from'] or created_date > filters['date_to']:
                    return False
        except (ValueError, TypeError):
            # If date parsing fails, don't filter based on date
            pass
        
        return True
    
    def reset_all_filters_to_defaults(self):
        """
        Reset ALL filters to their default values including age threshold and day type.
        Only called on app startup and snapshot refresh.
        """
        # Clear text filters
        self.vm_name_filter.clear()
        self.snapshot_search_filter.clear()
        
        # Reset dropdown filters
        self.vcenter_filter.setCurrentIndex(0)
        self.created_by_filter.setCurrentIndex(0)
        self.snapshot_type_filter.setCurrentIndex(0)
        
        # Reset date filters to default range (last 30 days)
        self.date_from_filter.setDate(QDate.currentDate().addDays(-30))
        self.date_to_filter.setDate(QDate.currentDate())
        
        # Reset age threshold to default
        self.age_threshold_spinbox.setValue(3)
        self.day_type_combo.setCurrentText("business days")
    
    def set_patching_filter(self, enabled):
        """
        Placeholder method for compatibility with main window.
        Patching filter is now handled by the main window checkbox only.
        """
        pass
    
    def get_patching_filter(self):
        """
        Placeholder method for compatibility with main window.
        Always returns False since patching filter is handled elsewhere.
        """
        return False
    
    def get_age_threshold(self):
        """
        Get the current age threshold for highlighting snapshots.
        
        Returns:
            int: Age threshold in business days
        """
        return self.age_threshold_spinbox.value()
    
    def set_age_threshold(self, days):
        """
        Set the age threshold for highlighting snapshots.
        
        Args:
            days (int): Age threshold in business days
        """
        self.age_threshold_spinbox.setValue(days)
    
    def get_day_type(self):
        """
        Get the current day type (business days or calendar days).
        
        Returns:
            str: "business days" or "calendar days"
        """
        return self.day_type_combo.currentText()
    
    def set_day_type(self, day_type):
        """
        Set the day type for age calculations.
        
        Args:
            day_type (str): "business days" or "calendar days"
        """
        self.day_type_combo.setCurrentText(day_type)