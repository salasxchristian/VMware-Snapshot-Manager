import unittest
import tempfile
import os
from unittest.mock import patch
from vmware_snapshot_manager import ConfigManager

class TestConfigManager(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures before each test method."""
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        self.temp_file.close()
        self.config_manager = ConfigManager()
        self.config_manager.config_file = self.temp_file.name
    
    def tearDown(self):
        """Clean up after each test method."""
        if os.path.exists(self.temp_file.name):
            os.unlink(self.temp_file.name)
    
    def test_save_load_servers_successfully(self):
        """Test saving and loading server configurations successfully."""
        test_servers = {
            'vcenter1.example.com': 'admin@domain.com',
            'vcenter2.example.com': 'user@company.com', 
            'vcenter3.local': 'administrator'
        }
        
        # Save servers
        self.config_manager.save_servers(test_servers)
        
        # Verify file was created
        self.assertTrue(os.path.exists(self.temp_file.name))
        
        # Load servers
        loaded_servers = self.config_manager.load_servers()
        
        # Verify data matches
        self.assertEqual(loaded_servers, test_servers)
    
    def test_save_load_empty_servers(self):
        """Test saving and loading empty server list."""
        empty_servers = {}
        
        self.config_manager.save_servers(empty_servers)
        loaded_servers = self.config_manager.load_servers()
        
        self.assertEqual(loaded_servers, empty_servers)
    
    def test_load_nonexistent_file(self):
        """Test loading from non-existent config file returns empty dict."""
        # Don't create any file
        self.config_manager.config_file = "/nonexistent/path/config.json"
        
        loaded_servers = self.config_manager.load_servers()
        
        self.assertEqual(loaded_servers, {})
    
    def test_load_invalid_json_file(self):
        """Test loading from corrupted/invalid JSON file returns empty dict."""
        # Create file with invalid JSON
        with open(self.temp_file.name, 'w') as f:
            f.write("{ invalid json content }")
        
        loaded_servers = self.config_manager.load_servers()
        
        # Should return empty dict when JSON is invalid
        self.assertEqual(loaded_servers, {})
    
    def test_load_json_without_servers_key(self):
        """Test loading JSON file without 'servers' key returns empty dict."""
        # Create valid JSON but without 'servers' key
        with open(self.temp_file.name, 'w') as f:
            f.write('{"other_config": "value"}')
        
        loaded_servers = self.config_manager.load_servers()
        
        # Should return empty dict when 'servers' key is missing
        self.assertEqual(loaded_servers, {})
    
    @patch('vmware_snapshot_manager.keyring')
    def test_save_password_success(self, mock_keyring):
        """Test saving password to keyring successfully."""
        mock_keyring.set_password.return_value = None
        
        result = self.config_manager.save_password('vcenter1.com', 'admin', 'password123')
        
        self.assertTrue(result)
        mock_keyring.set_password.assert_called_once_with(
            'vmware_snapshot_manager', 
            'vcenter1.com:admin', 
            'password123'
        )
    
    @patch('vmware_snapshot_manager.keyring')
    def test_save_password_failure(self, mock_keyring):
        """Test saving password to keyring with error."""
        mock_keyring.set_password.side_effect = Exception("Keyring error")
        
        result = self.config_manager.save_password('vcenter1.com', 'admin', 'password123')
        
        self.assertFalse(result)
    
    @patch('vmware_snapshot_manager.keyring')
    def test_get_password_success(self, mock_keyring):
        """Test retrieving password from keyring successfully."""
        mock_keyring.get_password.return_value = 'password123'
        
        password = self.config_manager.get_password('vcenter1.com', 'admin')
        
        self.assertEqual(password, 'password123')
        mock_keyring.get_password.assert_called_once_with(
            'vmware_snapshot_manager', 
            'vcenter1.com:admin'
        )
    
    @patch('vmware_snapshot_manager.keyring')
    def test_get_password_failure(self, mock_keyring):
        """Test retrieving password from keyring with error."""
        mock_keyring.get_password.side_effect = Exception("Keyring error")
        
        password = self.config_manager.get_password('vcenter1.com', 'admin')
        
        self.assertIsNone(password)
    
    @patch('builtins.open')
    def test_save_servers_file_permission_error(self, mock_open):
        """Test saving servers with file permission error."""
        mock_open.side_effect = PermissionError("Permission denied")
        
        test_servers = {'vcenter1.com': 'admin'}
        
        # Should not raise exception, just handle gracefully
        self.config_manager.save_servers(test_servers)
        
        # Verify open was attempted
        mock_open.assert_called_once()
    
    @patch('builtins.open')
    def test_load_servers_file_permission_error(self, mock_open):
        """Test loading servers with file permission error."""
        mock_open.side_effect = PermissionError("Permission denied")
        
        # Should handle gracefully and return empty dict
        with patch('os.path.exists', return_value=True):
            result = self.config_manager.load_servers()
        
        self.assertEqual(result, {})

if __name__ == '__main__':
    unittest.main()