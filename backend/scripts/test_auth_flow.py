import os
import httpx

BASE_URL = "http://127.0.0.1:8000"

EMAIL = os.getenv("VERIREVIEW_TEST_EMAIL")
PASSWORD = os.getenv("VERIREVIEW_TEST_PASSWORD")

if not EMAIL or not PASSWORD:
    raise SystemExit("Test credentials are missing from environment variables.")

print("\n=== VeriReview Authentication Tests ===\n")

with httpx.Client(base_url=BASE_URL) as client:

    # 1. Login
    response = client.post(
        "/api/v1/auth/login",
        json={
            "identifier": EMAIL,
            "password": PASSWORD,
        },
    )

    print("1. Login:", response.status_code)

    if response.status_code != 200:
        raise SystemExit("Login failed. Check the test account.")

    access_token = response.json()["access_token"]

    # 2. Protected user endpoint
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    print("2. Protected /me:", response.status_code)

    # 3. Save original refresh token
    original_refresh = client.cookies.get(
        "verireview_refresh_token"
    )

    # 4. Refresh token rotation
    response = client.post(
        "/api/v1/auth/refresh",
        headers={"Origin": "http://localhost:5173"},
    )

    print("3. Refresh rotation:", response.status_code)

    if response.status_code != 200:
        raise SystemExit("Refresh rotation failed.")

    rotated_refresh = client.cookies.get(
        "verireview_refresh_token"
    )

    # 5. Reuse old refresh token
    response = client.post(
        "/api/v1/auth/refresh",
        headers={
            "Origin": "http://localhost:5173",
            "Cookie": f"verireview_refresh_token={original_refresh}",
        },
    )

    print("4. Reuse detection:", response.status_code)

    # 6. Check whether the rotated token's family was revoked
    response = client.post(
        "/api/v1/auth/refresh",
        headers={
            "Origin": "http://localhost:5173",
            "Cookie": f"verireview_refresh_token={rotated_refresh}",
        },
    )

    print("5. Family revocation:", response.status_code)

    # 7. Logout
    response = client.post(
        "/api/v1/auth/logout",
        headers={"Origin": "http://localhost:5173"},
    )

    print("6. Logout:", response.status_code)

print("\n=== Tests completed ===")