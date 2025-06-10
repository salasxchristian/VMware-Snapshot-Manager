import unittest
from unittest.mock import MagicMock
from vmware_snapshot_manager import ProgressTracker

class TestProgressTracker(unittest.TestCase):
    def test_emit_progress_with_details(self):
        """Test ProgressTracker message formatting with details."""
        mock_signal = MagicMock()
        
        ProgressTracker.emit_progress(
            mock_signal, 
            current=3, 
            total=10, 
            operation="Processing VMs", 
            details="server1.example.com"
        )
        
        mock_signal.emit.assert_called_once_with(
            3, 10, "Processing VMs: server1.example.com (3/10)"
        )
    
    def test_emit_progress_without_details(self):
        """Test ProgressTracker message formatting without details."""
        mock_signal = MagicMock()
        
        ProgressTracker.emit_progress(
            mock_signal, 
            current=7, 
            total=15, 
            operation="Deleting snapshots"
        )
        
        mock_signal.emit.assert_called_once_with(
            7, 15, "Deleting snapshots (7/15)"
        )
    
    def test_emit_progress_edge_cases(self):
        """Test ProgressTracker with edge cases."""
        mock_signal = MagicMock()
        
        # Test with zero values
        ProgressTracker.emit_progress(mock_signal, 0, 0, "Starting")
        mock_signal.emit.assert_called_with(0, 0, "Starting (0/0)")
        
        # Test with single item
        ProgressTracker.emit_progress(mock_signal, 1, 1, "Complete")
        mock_signal.emit.assert_called_with(1, 1, "Complete (1/1)")

if __name__ == '__main__':
    unittest.main()