#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from access.models import User

users = User.objects.all().order_by('username')
print("\n" + "="*120)
print(f"{'Username':<15} | {'Full Name':<20} | {'Role':<25} | {'Tier':<25} | {'Superuser':<10}")
print("="*120)
for u in users:
    role_name = u.role.name if u.role else "None"
    tier_name = u.tier.name if u.tier else "None"
    print(f"{u.username:<15} | {u.get_full_name():<20} | {role_name:<25} | {tier_name:<25} | {str(u.is_superuser):<10}")
print("="*120 + "\n")
