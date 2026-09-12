"""Legacy manual smoke test.

Run this file directly after starting the API; it is intentionally excluded
from normal pytest collection because it performs live HTTP requests.
"""
import pytest

if "pytest" in __import__("sys").modules:
    pytest.skip("legacy live-server smoke test; run directly with Python", allow_module_level=True)

import requests
import sys
import json

base_url = "http://localhost:8000/api/v1"

import random

# Register as a new user
email = f"test_{random.randint(1000, 9999)}@test.com"
res = requests.post(f"{base_url}/auth/register", json={"email": email, "password": "Password1", "full_name": "Test User", "account_type": "organization", "organization_name": "Test Org"})
if res.status_code != 201:
    print("Register failed", res.text)
    sys.exit(1)

res = requests.post(f"{base_url}/auth/login/workspace", json={"email": email, "password": "Password1", "workspace_code": "COMP-0001"})
if res.status_code != 200:
    res = requests.post(f"{base_url}/auth/login", json={"email": email, "password": "Password1"})
    
if res.status_code != 200:
    print("Login failed", res.text)
    sys.exit(1)

token = res.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# Get companies
res = requests.get(f"{base_url}/companies", headers=headers)
print("Companies:", res.json())
cid = res.json()[0]['public_id']

# Get projects
res = requests.get(f"{base_url}/projects", headers=headers)
print("Projects:", res.json())
pid = res.json()[0]['public_id']

# Create meeting
res = requests.post(f"{base_url}/companies/{cid}/meetings", json={"title": "Test", "project_id": pid}, headers=headers)
print("Create meeting:", res.status_code, res.text)
