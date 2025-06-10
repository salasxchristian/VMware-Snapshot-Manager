import unittest
from vmware_snapshot_manager import SnapshotFetchWorker

class TestUtilityFunctions(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures."""
        self.worker = SnapshotFetchWorker({})
    
    def test_extract_creator_basic_patterns(self):
        """Test username extraction from basic description patterns."""
        test_cases = [
            ("Created by: admin", "admin"),
            ("(Created by: john)", "john"),
            ("User: alice", "alice"),
            ("By: bob", "bob"),
            ("Monthly patching snapshot Created by: administrator", "administrator"),
        ]
        
        for description, expected in test_cases:
            with self.subTest(description=description):
                result = self.worker.extract_creator_from_description(description)
                self.assertEqual(result, expected)
    
    def test_extract_creator_word_characters_only(self):
        """Test username extraction only captures word characters."""
        # The current implementation only captures \w+ (word characters)
        test_cases = [
            ("Created by: user@domain.com", "user"),  # Stops at @
            ("Created by: DOMAIN\\administrator", "DOMAIN"),  # Stops at \
            ("Created by: first.last", "first"),  # Stops at .
            ("(Created by: service-account)", "service"),  # Stops at -
        ]
        
        for description, expected in test_cases:
            with self.subTest(description=description):
                result = self.worker.extract_creator_from_description(description)
                self.assertEqual(result, expected)
    
    def test_extract_creator_case_insensitive(self):
        """Test that username extraction is case insensitive."""
        test_cases = [
            ("CREATED BY: admin", "admin"),
            ("created by: testuser", "testuser"),
            ("Created By: MixedCase", "MixedCase"),
            ("USER: lowercase", "lowercase"),
        ]
        
        for description, expected in test_cases:
            with self.subTest(description=description):
                result = self.worker.extract_creator_from_description(description)
                self.assertEqual(result, expected)
    
    def test_extract_creator_edge_cases(self):
        """Test username extraction edge cases."""
        test_cases = [
            ("", "Unknown"),
            (None, "Unknown"),
            ("No creator information here", "Unknown"),
            ("Random text without patterns", "Unknown"),
            ("Created by:", "Unknown"),  # Empty creator
        ]
        
        for description, expected in test_cases:
            with self.subTest(description=description):
                result = self.worker.extract_creator_from_description(description)
                self.assertEqual(result, expected)
    
    def test_extract_creator_multiple_patterns(self):
        """Test descriptions with multiple potential patterns."""
        # Should pick the first match
        description = "Created by: admin, also mentions User: guest"
        result = self.worker.extract_creator_from_description(description)
        self.assertEqual(result, "admin")
    
    def test_extract_creator_whitespace_handling(self):
        """Test handling of whitespace around usernames."""
        test_cases = [
            ("Created by:   admin   ", "admin"),
            ("(Created by: \t testuser \t)", "testuser"),
            ("User:     service     ", "service"),  # Only word characters captured
        ]
        
        for description, expected in test_cases:
            with self.subTest(description=description):
                result = self.worker.extract_creator_from_description(description)
                self.assertEqual(result, expected)

if __name__ == '__main__':
    unittest.main()