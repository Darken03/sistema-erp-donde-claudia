
#!/usr/bin/env python
"""Test the /ipb/ endpoint after database recovery."""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'system_erp.settings')
django.setup()

from django.test import RequestFactory
from core.views import ipb

# Simulate request to /ipb/
request = RequestFactory().get('/ipb/')
request.session = {}

try:
    response = ipb(request)
    print(f"Response status: {response.status_code}")
    print(f"Response content type: {response.get('Content-Type', 'N/A')}")
    print("SUCCESS: /ipb/ endpoint is working!")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
