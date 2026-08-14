#!/usr/bin/env python
"""Test all demo user logins."""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import authenticate
from access.models import User

demo_accounts = [
    ('manager', 'demo12345'),
    ('lead', 'demo12345'),
    ('picker', 'demo12345'),
    ('foreman', 'demo12345'),
    ('admin', 'demo12345'),
    ('safety', 'demo12345'),
]

print("\n" + "="*70)
print("Testing all demo account logins")
print("="*70)

all_pass = True
for username, password in demo_accounts:
    user = authenticate(username=username, password=password)
    if user is not None:
        print(f"✓ {username:<15} - Authenticated successfully")
        print(f"  → Name: {user.get_full_name()}, Role: {user.role}, Tier: {user.tier}")
    else:
        print(f"✗ {username:<15} - FAILED to authenticate")
        all_pass = False

print("="*70)
if all_pass:
    print("✓ All demo logins are working!")
else:
    print("✗ Some logins failed!")
print("="*70 + "\n")
