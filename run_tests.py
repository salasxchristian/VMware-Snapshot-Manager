#!/usr/bin/env python3
"""
Test runner for VMware Snapshot Manager
Runs all test files and provides a summary.
"""

import unittest
import sys

def run_all_tests():
    """Run all test files and return results."""
    
    # Discover and run all tests
    loader = unittest.TestLoader()
    
    # Load test modules
    test_modules = [
        'test_config_manager',
        'test_progress_tracker', 
        'test_utilities'
    ]
    
    suite = unittest.TestSuite()
    
    for module_name in test_modules:
        try:
            tests = loader.loadTestsFromName(module_name)
            suite.addTests(tests)
            print(f"[OK] Loaded tests from {module_name}")
        except Exception as e:
            print(f"[FAIL] Failed to load {module_name}: {e}")
            return False
    
    # Run tests with detailed output
    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout, buffer=True)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "="*50)
    print("TEST SUMMARY")
    print("="*50)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Success rate: {((result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100):.1f}%")
    
    if result.failures:
        print(f"\nFAILURES ({len(result.failures)}):")
        for test, _ in result.failures:
            print(f"  - {test}")
    
    if result.errors:
        print(f"\nERRORS ({len(result.errors)}):")
        for test, _ in result.errors:
            print(f"  - {test}")
    
    return len(result.failures) == 0 and len(result.errors) == 0

if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)