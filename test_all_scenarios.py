import requests
import json
import sys

BASE_URL = "https://meetvault-api.onrender.com/api/v1"

def run_tests():
    print("==================================================")
    print("TASK 8 MULTI-DEVICE & AUTHENTICATION TEST SUITE")
    print("==================================================")

    # ──────────────────────────────────────────────────────────
    # TEST A — HOST CREATES MEETING
    # ──────────────────────────────────────────────────────────
    print("\n[TEST A] Host Authentication & Meeting Creation...")
    host_email = "device_a_host@example.com"
    host_pass = "HostSecret123!"

    # Host Sign-up / Sign-in
    r = requests.post(f"{BASE_URL}/auth/login/personal", json={"email": host_email, "password": host_pass})
    if r.status_code != 200:
        requests.post(f"{BASE_URL}/auth/register", json={
            "full_name": "Device A Host",
            "email": host_email,
            "password": host_pass,
            "account_type": "personal"
        })
        r = requests.post(f"{BASE_URL}/auth/login/personal", json={"email": host_email, "password": host_pass})

    assert r.status_code == 200, f"Host login failed: {r.text}"
    host_tokens = r.json()
    host_access = host_tokens["access_token"]
    host_refresh = host_tokens["refresh_token"]
    print(f"  [OK] Host signed in successfully (access_token={host_access[:15]}...)")

    # Host Creates Meeting via POST /meetings/personal
    r_create = requests.post(
        f"{BASE_URL}/meetings/personal",
        json={"title": "Multi-Device Test Sync"},
        headers={"Authorization": f"Bearer {host_access}"}
    )
    assert r_create.status_code in (200, 201), f"Meeting creation failed: {r_create.text}"
    create_data = r_create.json()
    meeting_id = create_data["public_id"]
    invite_code = create_data["invite_code"]
    
    assert invite_code and invite_code.startswith("MTG-"), f"Invalid invite code returned: {invite_code}"
    print(f"  [OK] Real meeting created: meeting_id={meeting_id}, invite_code={invite_code}")

    # Verify Host joins room
    r_host_join = requests.post(
        f"{BASE_URL}/meetings/{meeting_id}/room/join",
        headers={"Authorization": f"Bearer {host_access}"}
    )
    assert r_host_join.status_code == 200, f"Host room join failed: {r_host_join.text}"
    print(f"  [OK] Host entered room successfully.")

    # ──────────────────────────────────────────────────────────
    # TEST B — PARTICIPANT JOINS FROM DEVICE B
    # ──────────────────────────────────────────────────────────
    print("\n[TEST B] Device B Participant Joins via Invite Code...")
    part_email = "device_b_participant@example.com"
    part_pass = "PartSecret123!"

    # Participant Sign-up / Sign-in on Device B
    r_p = requests.post(f"{BASE_URL}/auth/login/personal", json={"email": part_email, "password": part_pass})
    if r_p.status_code != 200:
        requests.post(f"{BASE_URL}/auth/register", json={
            "full_name": "Device B Participant",
            "email": part_email,
            "password": part_pass,
            "account_type": "personal"
        })
        r_p = requests.post(f"{BASE_URL}/auth/login/personal", json={"email": part_email, "password": part_pass})

    assert r_p.status_code == 200, f"Participant login failed: {r_p.text}"
    part_tokens = r_p.json()
    part_access = part_tokens["access_token"]
    print(f"  [OK] Device B signed in with own account (access_token={part_access[:15]}...)")

    # Participant Joins using Host's invite_code via POST /meetings/join
    r_join = requests.post(
        f"{BASE_URL}/meetings/join",
        json={"invite_code": invite_code},
        headers={"Authorization": f"Bearer {part_access}"}
    )
    assert r_join.status_code == 200, f"Device B join failed: {r_join.text}"
    join_data = r_join.json()
    print(f"  [OK] Device B joined meeting {invite_code} successfully!")
    print(f"    - room_name: {join_data.get('room_name')}")
    print(f"    - role: {join_data.get('participant', {}).get('role')}")
    print(f"    - livekit_url: {join_data.get('livekit_url')}")

    # ──────────────────────────────────────────────────────────
    # TEST C — EXPIRED ACCESS TOKEN & REFRESH FLOW
    # ──────────────────────────────────────────────────────────
    print("\n[TEST C] Refreshing Access Token using Refresh Token...")
    r_ref = requests.post(
        f"{BASE_URL}/auth/refresh",
        json={"refresh_token": host_refresh}
    )
    assert r_ref.status_code == 200, f"Token refresh failed: {r_ref.text}"
    new_tokens = r_ref.json()
    new_access = new_tokens["access_token"]
    new_refresh = new_tokens["refresh_token"]
    assert new_access and new_refresh, "Refresh endpoint must return access_token and refresh_token"
    print(f"  [OK] Token refresh succeeded! (new access_token={new_access[:15]}...)")

    # Verify new access token works for GET /meetings/history
    r_hist = requests.get(
        f"{BASE_URL}/meetings/history",
        headers={"Authorization": f"Bearer {new_access}"}
    )
    assert r_hist.status_code == 200, f"History request with new token failed: {r_hist.text}"
    print(f"  [OK] GET /meetings/history succeeded with refreshed token.")

    # ──────────────────────────────────────────────────────────
    # TEST D — INVALID REFRESH TOKEN
    # ──────────────────────────────────────────────────────────
    print("\n[TEST D] Invalid Refresh Token Verification...")
    r_bad_ref = requests.post(
        f"{BASE_URL}/auth/refresh",
        json={"refresh_token": "invalid_refresh_token_12345_xyz"}
    )
    assert r_bad_ref.status_code == 401, f"Expected 401 for invalid refresh token, got {r_bad_ref.status_code}"
    print(f"  [OK] Invalid refresh token correctly rejected with HTTP 401.")

    # ──────────────────────────────────────────────────────────
    # TEST E — INVALID MEETING CODE
    # ──────────────────────────────────────────────────────────
    print("\n[TEST E] Invalid Meeting Code Verification...")
    r_invalid_code = requests.post(
        f"{BASE_URL}/meetings/join",
        json={"invite_code": "MTG-INVALID999"},
        headers={"Authorization": f"Bearer {part_access}"}
    )
    assert r_invalid_code.status_code == 404, f"Expected 404 for invalid meeting code, got {r_invalid_code.status_code}"
    err_detail = r_invalid_code.json().get("detail", "")
    print(f"  [OK] Invalid code correctly returned HTTP 404: '{err_detail}'")
    assert err_detail != "Could not validate credentials", "Should NOT return credential error for invalid meeting code"

    print("\n==================================================")
    print("ALL 5 VERIFICATION TESTS PASSED PERFECTLY!")
    print("==================================================")

if __name__ == "__main__":
    run_tests()
