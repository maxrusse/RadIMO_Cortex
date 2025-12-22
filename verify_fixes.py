#!/usr/bin/env python3
"""
Verification script to check all fixes are in place.
Run this after pulling the latest code to verify the deployment is ready.
"""
import sys

def check_line(filepath, line_num, expected_content):
    """Check if a specific line contains expected content."""
    try:
        with open(filepath, 'r') as f:
            lines = f.readlines()
            if line_num <= len(lines):
                actual = lines[line_num - 1].strip()
                if expected_content in actual:
                    return True, actual
                else:
                    return False, actual
            return False, "Line not found"
    except Exception as e:
        return False, str(e)

checks = [
    {
        'name': 'routes.py line 1042 - @admin_required (was @requires_auth)',
        'file': 'routes.py',
        'line': 1042,
        'expected': '@admin_required'
    },
    {
        'name': 'routes.py line 1065 - @admin_required (was @requires_auth)',
        'file': 'routes.py',
        'line': 1065,
        'expected': '@admin_required'
    },
    {
        'name': 'routes.py line 1091 - @admin_required (was @requires_auth)',
        'file': 'routes.py',
        'line': 1091,
        'expected': '@admin_required'
    },
    {
        'name': 'routes.py line 1108 - @admin_required (was @requires_auth)',
        'file': 'routes.py',
        'line': 1108,
        'expected': '@admin_required'
    },
    {
        'name': 'routes.py line 537 - APP_CONFIG (was app.APP_CONFIG)',
        'file': 'routes.py',
        'line': 537,
        'expected': 'scheduler_conf = APP_CONFIG.get'
    },
    {
        'name': 'ops_check.py - proper imports',
        'file': 'ops_check.py',
        'line': 11,
        'expected': 'from config import'
    },
]

print("=" * 70)
print("VERIFYING ALL FIXES")
print("=" * 70)

all_passed = True
for check in checks:
    passed, actual = check_line(check['file'], check['line'], check['expected'])
    status = '✓' if passed else '✗'
    print(f"{status} {check['name']}")
    if not passed:
        print(f"   Expected: {check['expected']}")
        print(f"   Got: {actual}")
        all_passed = False

print("=" * 70)
if all_passed:
    print("✓ ALL CHECKS PASSED - Code is ready!")
    sys.exit(0)
else:
    print("✗ SOME CHECKS FAILED - Please pull latest changes!")
    sys.exit(1)
