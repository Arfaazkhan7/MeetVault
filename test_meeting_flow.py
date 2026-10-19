import requests
import json
import sys

BASE_URL = "https://meetvault-api.onrender.com/api/v1"

def run_test():
    print("=== Testing MeetVault Backend Auth & Join Flow ===")
    
    # 1. Host Login/Register
    host_email = "test_host_101@example.com"
    host_pass = "Password123!"
    
    print("\n1. Host Signing In...")
    r = requests.post(f"{BASE_URL}/auth/login/personal", json={"email": host_email, "password": host_pass})
    if r.status_code != 200:
        print("Registering Host via /auth/register...")
        r_reg = requests.post(f"{BASE_URL}/auth/register", json={
            "full_name": "Test Host",
            "email": host_email,
            "password": host_pass,
            "account_type": "personal"
        })
        print(f"Register status: {r_reg.status_code}, body: {r_reg.text}")
        r = requests.post(f"{BASE_URL}/auth/login/personal", json={"email": host_email, "password": host_pass})
        
    print(f"Host login status: {r.status_code}")
    if r.status_code != 200:
        print(f"FAILED Host Login: {r.text}")
        return
    
    host_data = r.json()
    host_token = host_data.get("access_token")
    print(f"Host token received: {host_token[:20]}...")
    
    # Verify Host Auth
    r_me = requests.get(f"{BASE_URL}/auth/me", headers={"Authorization": f"Bearer {host_token}"})
    print(f"Host /auth/me status: {r_me.status_code}, user: {r_me.json().get('email')}")
    
    # 2. Host Creates Personal Meeting
    print("\n2. Host Creating Personal Meeting via /meetings/personal...")
    r_meet = requests.post(
        f"{BASE_URL}/meetings/personal",
        json={"title": "Test Auth & Join Meeting", "description": "Automated Test"},
        headers={"Authorization": f"Bearer {host_token}"}
    )
    print(f"Create meeting status: {r_meet.status_code}")
    print(f"Create meeting response: {r_meet.text}")
    if r_meet.status_code not in (200, 201):
        print("FAILED Create Meeting")
        return
        
    meet_data = r_meet.json()
    invite_code = meet_data.get("invite_code")
    meeting_id = meet_data.get("public_id")
    print(f"Meeting created: ID={meeting_id}, invite_code={invite_code}")
    
    # 3. Attendee Login/Register
    attendee_email = "test_attendee_101@example.com"
    attendee_pass = "Password123!"
    
    print("\n3. Attendee Signing In...")
    r_att = requests.post(f"{BASE_URL}/auth/login/personal", json={"email": attendee_email, "password": attendee_pass})
    if r_att.status_code != 200:
        print("Registering Attendee via /auth/register...")
        r_reg = requests.post(f"{BASE_URL}/auth/register", json={
            "full_name": "Test Attendee",
            "email": attendee_email,
            "password": attendee_pass,
            "account_type": "personal"
        })
        print(f"Register status: {r_reg.status_code}, body: {r_reg.text}")
        r_att = requests.post(f"{BASE_URL}/auth/login/personal", json={"email": attendee_email, "password": attendee_pass})
        
    print(f"Attendee login status: {r_att.status_code}")
    if r_att.status_code != 200:
        print(f"FAILED Attendee Login: {r_att.text}")
        return
        
    attendee_data = r_att.json()
    attendee_token = attendee_data.get("access_token")
    print(f"Attendee token received: {attendee_token[:20]}...")
    
    # Verify Attendee Auth
    r_att_me = requests.get(f"{BASE_URL}/auth/me", headers={"Authorization": f"Bearer {attendee_token}"})
    print(f"Attendee /auth/me status: {r_att_me.status_code}, user: {r_att_me.json().get('email')}")
    
    # 4. Attendee Joins Meeting by invite_code
    print(f"\n4. Attendee Joining Meeting using code '{invite_code}'...")
    r_join = requests.post(
        f"{BASE_URL}/meetings/join",
        json={"invite_code": invite_code},
        headers={"Authorization": f"Bearer {attendee_token}"}
    )
    print(f"Join meeting response status: {r_join.status_code}")
    print(f"Join meeting response body: {r_join.text}")

if __name__ == "__main__":
    run_test()
