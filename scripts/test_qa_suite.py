import asyncio
import json
import requests
import sys

BASE_URL = "http://127.0.0.1:8000/api/v1"

results = []

def record(test_id, category, name, passed, details):
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] [{category}] {test_id}: {name} - {details}")
    results.append({
        "id": test_id,
        "category": category,
        "name": name,
        "passed": passed,
        "details": details
    })

def run_qa_suite():
    print("=========================================================")
    print("      JROS BACKEND AUTOMATED QA & VERIFICATION SUITE      ")
    print("=========================================================")

    # 1. HEALTH CHECK
    try:
        r = requests.get(f"{BASE_URL}/health")
        passed = r.status_code == 200 and r.json().get("success") == True and r.json().get("data", {}).get("database", {}).get("status") == "healthy"
        record("TC-HLTH-01", "Health", "API & Database Health Ping", passed, f"Status: {r.status_code}, Body: {r.json()}")
    except Exception as e:
        record("TC-HLTH-01", "Health", "API & Database Health Ping", False, str(e))

    # 2. PUBLIC TENANTS LIST
    try:
        r = requests.get(f"{BASE_URL}/tenants/public")
        data = r.json().get("data", {}).get("tenants", [])
        passed = r.status_code == 200 and len(data) > 0
        record("TC-PUB-01", "Tenants", "Get Public Active Jewellery Stores", passed, f"Stores count: {len(data)}")
        tenant_id = data[0]["id"] if data else "tnt_default_sk"
    except Exception as e:
        record("TC-PUB-01", "Tenants", "Get Public Active Jewellery Stores", False, str(e))
        tenant_id = "tnt_default_sk"

    # 3. SUPERADMIN LOGIN
    sa_token = None
    try:
        payload = {"username": "superadmin@jros.com", "password": "SuperAdmin@123"}
        r = requests.post(f"{BASE_URL}/auth/login", json=payload)
        passed = r.status_code == 200 and "access_token" in r.json().get("data", {})
        if passed:
            sa_token = r.json()["data"]["access_token"]
        record("TC-AUTH-01", "Auth", "SuperAdmin Login", passed, f"Status: {r.status_code}")
    except Exception as e:
        record("TC-AUTH-01", "Auth", "SuperAdmin Login", False, str(e))

    # 4. CUSTOMER SIGNUP VALIDATIONS
    # 4.1 Missing Fields (No email or phone)
    try:
        payload = {"name": "Invalid User", "password": "Password123", "tenant_id": tenant_id}
        r = requests.post(f"{BASE_URL}/auth/signup", json=payload)
        passed = r.status_code == 400 and r.json().get("success") == False
        record("TC-SIGNUP-01", "Signup", "Signup missing email & phone validation", passed, f"Status: {r.status_code}, Msg: {r.json().get('message')}")
    except Exception as e:
        record("TC-SIGNUP-01", "Signup", "Signup missing email & phone validation", False, str(e))

    # 4.2 Invalid Tenant ID
    try:
        payload = {"name": "Test User", "email": "invalidtenant@example.com", "phone": "9000000001", "password": "Password123", "tenant_id": "tnt_non_existent"}
        r = requests.post(f"{BASE_URL}/auth/signup", json=payload)
        passed = r.status_code == 404
        record("TC-SIGNUP-02", "Signup", "Signup with invalid tenant ID", passed, f"Status: {r.status_code}, Msg: {r.json().get('message')}")
    except Exception as e:
        record("TC-SIGNUP-02", "Signup", "Signup with invalid tenant ID", False, str(e))

    # 4.3 Valid Customer Signup
    cust_email = "qa_customer_01@example.com"
    cust_phone = "9876500001"
    cust_pass = "Customer@123"
    cust_user_id = None
    try:
        payload = {
            "name": "QA Test Customer 1",
            "email": cust_email,
            "phone": cust_phone,
            "password": cust_pass,
            "tenant_id": tenant_id
        }
        r = requests.post(f"{BASE_URL}/auth/signup", json=payload)
        passed = r.status_code == 201 and "user" in r.json().get("data", {})
        if passed:
            cust_user_id = r.json()["data"]["user"]["id"]
        record("TC-SIGNUP-03", "Signup", "Valid Customer Registration", passed, f"Status: {r.status_code}, UserID: {cust_user_id}")
    except Exception as e:
        record("TC-SIGNUP-03", "Signup", "Valid Customer Registration", False, str(e))

    # 4.4 Duplicate Email Signup
    try:
        payload = {
            "name": "Duplicate Email User",
            "email": cust_email,
            "phone": "9876500002",
            "password": "Password123",
            "tenant_id": tenant_id
        }
        r = requests.post(f"{BASE_URL}/auth/signup", json=payload)
        passed = r.status_code == 409
        record("TC-SIGNUP-04", "Signup", "Duplicate Email Registration Rejection", passed, f"Status: {r.status_code}, Msg: {r.json().get('message')}")
    except Exception as e:
        record("TC-SIGNUP-04", "Signup", "Duplicate Email Registration Rejection", False, str(e))

    # 4.5 Duplicate Phone Signup
    try:
        payload = {
            "name": "Duplicate Phone User",
            "email": "unique_email_99@example.com",
            "phone": cust_phone,
            "password": "Password123",
            "tenant_id": tenant_id
        }
        r = requests.post(f"{BASE_URL}/auth/signup", json=payload)
        passed = r.status_code == 409
        record("TC-SIGNUP-05", "Signup", "Duplicate Phone Registration Rejection", passed, f"Status: {r.status_code}, Msg: {r.json().get('message')}")
    except Exception as e:
        record("TC-SIGNUP-05", "Signup", "Duplicate Phone Registration Rejection", False, str(e))

    # 5. AUTHENTICATION & LOGIN
    # 5.1 Invalid Credentials Login
    try:
        payload = {"username": cust_email, "password": "WrongPassword123"}
        r = requests.post(f"{BASE_URL}/auth/login", json=payload)
        passed = r.status_code == 401
        record("TC-AUTH-02", "Auth", "Invalid Password Login Rejection", passed, f"Status: {r.status_code}")
    except Exception as e:
        record("TC-AUTH-02", "Auth", "Invalid Password Login Rejection", False, str(e))

    # 5.2 Valid Customer Login (Email)
    cust_token = None
    cust_refresh_token = None
    try:
        payload = {"username": cust_email, "password": cust_pass}
        r = requests.post(f"{BASE_URL}/auth/login", json=payload)
        data = r.json().get("data", {})
        passed = r.status_code == 200 and "access_token" in data and "refresh_token" in data
        if passed:
            cust_token = data["access_token"]
            cust_refresh_token = data["refresh_token"]
        record("TC-AUTH-03", "Auth", "Valid Customer Login via Email", passed, f"Status: {r.status_code}")
    except Exception as e:
        record("TC-AUTH-03", "Auth", "Valid Customer Login via Email", False, str(e))

    # 5.3 Valid Customer Login (Phone)
    try:
        payload = {"username": cust_phone, "password": cust_pass}
        r = requests.post(f"{BASE_URL}/auth/login", json=payload)
        passed = r.status_code == 200 and "access_token" in r.json().get("data", {})
        record("TC-AUTH-04", "Auth", "Valid Customer Login via Phone", passed, f"Status: {r.status_code}")
    except Exception as e:
        record("TC-AUTH-04", "Auth", "Valid Customer Login via Phone", False, str(e))

    # 6. TOKEN SECURITY & DEPENDENCIES
    # 6.1 Missing Bearer Token
    try:
        r = requests.get(f"{BASE_URL}/users/me")
        passed = r.status_code == 401
        record("TC-SEC-01", "Security", "Missing Authorization Header Rejection", passed, f"Status: {r.status_code}")
    except Exception as e:
        record("TC-SEC-01", "Security", "Missing Authorization Header Rejection", False, str(e))

    # 6.2 Malformed JWT Token
    try:
        headers = {"Authorization": "Bearer invalid.jwt.token.string"}
        r = requests.get(f"{BASE_URL}/users/me", headers=headers)
        passed = r.status_code == 401
        record("TC-SEC-02", "Security", "Malformed JWT Token Rejection", passed, f"Status: {r.status_code}")
    except Exception as e:
        record("TC-SEC-02", "Security", "Malformed JWT Token Rejection", False, str(e))

    # 6.3 Valid Profile Retrieval
    try:
        headers = {"Authorization": f"Bearer {cust_token}"}
        r = requests.get(f"{BASE_URL}/users/me", headers=headers)
        user = r.json().get("data", {}).get("user", {})
        passed = r.status_code == 200 and user.get("email") == cust_email
        record("TC-SEC-03", "Security", "Authenticated User Profile Fetch", passed, f"Email: {user.get('email')}, Role: {user.get('role')}")
    except Exception as e:
        record("TC-SEC-03", "Security", "Authenticated User Profile Fetch", False, str(e))

    # 7. REFRESH TOKEN ROTATION & SECURITY
    # 7.1 Valid Refresh Token Rotation
    new_cust_token = None
    new_cust_refresh_token = None
    try:
        payload = {"refresh_token": cust_refresh_token}
        r = requests.post(f"{BASE_URL}/auth/refresh", json=payload)
        data = r.json().get("data", {})
        passed = r.status_code == 200 and "access_token" in data and "refresh_token" in data
        if passed:
            new_cust_token = data["access_token"]
            new_cust_refresh_token = data["refresh_token"]
        record("TC-RFRSH-01", "Refresh", "Valid Refresh Token Exchange", passed, f"Status: {r.status_code}")
    except Exception as e:
        record("TC-RFRSH-01", "Refresh", "Valid Refresh Token Exchange", False, str(e))

    # 7.2 Revoked Refresh Token Reuse Safeguard (Token Theft Mitigation)
    try:
        # Attempt to reuse the OLD revoked refresh token
        payload = {"refresh_token": cust_refresh_token}
        r = requests.post(f"{BASE_URL}/auth/refresh", json=payload)
        passed = r.status_code == 401 and "Security alert" in r.json().get("message", "")
        record("TC-RFRSH-02", "Refresh", "Revoked Token Reuse Theft Safeguard", passed, f"Status: {r.status_code}, Msg: {r.json().get('message')}")
    except Exception as e:
        record("TC-RFRSH-02", "Refresh", "Revoked Token Reuse Theft Safeguard", False, str(e))

    # Log in again to get fresh valid tokens for further tests
    try:
        payload = {"username": cust_email, "password": cust_pass}
        r = requests.post(f"{BASE_URL}/auth/login", json=payload)
        cust_token = r.json()["data"]["access_token"]
        cust_refresh_token = r.json()["data"]["refresh_token"]
    except Exception:
        pass

    # 8. CUSTOMER PROFILE MODULE
    headers = {"Authorization": f"Bearer {cust_token}"}
    # 8.1 Get Customer Profile
    try:
        r = requests.get(f"{BASE_URL}/customer/profile", headers=headers)
        prof = r.json().get("data", {}).get("profile", {})
        passed = r.status_code == 200 and prof.get("tenant_name") == "Sri Krishna Jewellers"
        record("TC-PROF-01", "Profile", "Get Customer Profile with Store Name", passed, f"Store: {prof.get('tenant_name')}")
    except Exception as e:
        record("TC-PROF-01", "Profile", "Get Customer Profile with Store Name", False, str(e))

    # 8.2 Update Customer Profile
    try:
        payload = {"name": "Updated QA Customer Name", "avatar_url": "https://example.com/avatar.png"}
        r = requests.put(f"{BASE_URL}/customer/profile", json=payload, headers=headers)
        prof = r.json().get("data", {}).get("profile", {})
        passed = r.status_code == 200 and prof.get("name") == "Updated QA Customer Name"
        record("TC-PROF-02", "Profile", "Update Customer Profile Details", passed, f"Updated Name: {prof.get('name')}")
    except Exception as e:
        record("TC-PROF-02", "Profile", "Update Customer Profile Details", False, str(e))

    # 8.3 Invalid Phone Number Format in Profile Update
    try:
        payload = {"phone": "12345"}
        r = requests.put(f"{BASE_URL}/customer/profile", json=payload, headers=headers)
        passed = r.status_code == 400
        record("TC-PROF-03", "Profile", "Invalid Phone Regex Validation", passed, f"Status: {r.status_code}")
    except Exception as e:
        record("TC-PROF-03", "Profile", "Invalid Phone Regex Validation", False, str(e))

    # 9. CUSTOMER KYC MODULE
    # 9.1 Initial KYC Status (None)
    try:
        r = requests.get(f"{BASE_URL}/customer/kyc", headers=headers)
        passed = r.status_code == 200 and r.json().get("data", {}).get("kyc") is None
        record("TC-KYC-01", "KYC", "Initial KYC Status Unsubmitted", passed, f"Status: {r.status_code}")
    except Exception as e:
        record("TC-KYC-01", "KYC", "Initial KYC Status Unsubmitted", False, str(e))

    # 9.2 Invalid PAN Format Submission
    try:
        payload = {"doc_type": "PAN", "doc_number": "INVALID_PAN_123"}
        r = requests.post(f"{BASE_URL}/customer/kyc", json=payload, headers=headers)
        passed = r.status_code == 400
        record("TC-KYC-02", "KYC", "Invalid PAN Format Rejection", passed, f"Status: {r.status_code}")
    except Exception as e:
        record("TC-KYC-02", "KYC", "Invalid PAN Format Rejection", False, str(e))

    # 9.3 Valid PAN Document Submission
    try:
        payload = {"doc_type": "PAN", "doc_number": "ABCDE1234F"}
        r = requests.post(f"{BASE_URL}/customer/kyc", json=payload, headers=headers)
        kyc = r.json().get("data", {}).get("kyc", {})
        passed = r.status_code == 201 and kyc.get("doc_number") == "ABCDE1234F" and kyc.get("status") == "Pending"
        record("TC-KYC-03", "KYC", "Valid PAN Document Submission", passed, f"KYC Status: {kyc.get('status')}")
    except Exception as e:
        record("TC-KYC-03", "KYC", "Valid PAN Document Submission", False, str(e))

    # 10. CUSTOMER ADDRESS MODULE
    # 10.1 Invalid Pincode Validation
    try:
        payload = {
            "name": "QA Address",
            "phone": "9876500001",
            "house": "123",
            "street": "Main Street",
            "area": "Downtown",
            "city": "Bengaluru",
            "state": "Karnataka",
            "pincode": "56000"  # Only 5 digits (invalid)
        }
        r = requests.post(f"{BASE_URL}/customer/addresses", json=payload, headers=headers)
        passed = r.status_code == 400
        record("TC-ADDR-01", "Address", "Invalid 5-digit Pincode Rejection", passed, f"Status: {r.status_code}")
    except Exception as e:
        record("TC-ADDR-01", "Address", "Invalid 5-digit Pincode Rejection", False, str(e))

    # 10.2 Valid Address Creation (First address auto-default)
    addr_id = None
    try:
        payload = {
            "name": "QA Main Address",
            "phone": "9876500001",
            "house": "Flat 402, Royal Residency",
            "street": "100ft Road",
            "area": "Indiranagar",
            "city": "Bengaluru",
            "state": "Karnataka",
            "pincode": "560038",
            "type": "Home"
        }
        r = requests.post(f"{BASE_URL}/customer/addresses", json=payload, headers=headers)
        addr = r.json().get("data", {}).get("address", {})
        passed = r.status_code == 201 and addr.get("is_default") == True
        if passed:
            addr_id = addr["id"]
        record("TC-ADDR-02", "Address", "Valid Address Creation (Auto Default)", passed, f"AddrID: {addr_id}, Default: {addr.get('is_default')}")
    except Exception as e:
        record("TC-ADDR-02", "Address", "Valid Address Creation (Auto Default)", False, str(e))

    # 10.3 Address Update
    try:
        payload = {"house": "Penthouse 501", "city": "Bengaluru"}
        r = requests.put(f"{BASE_URL}/customer/addresses/{addr_id}", json=payload, headers=headers)
        addr = r.json().get("data", {}).get("address", {})
        passed = r.status_code == 200 and addr.get("house") == "Penthouse 501"
        record("TC-ADDR-03", "Address", "Update Existing Customer Address", passed, f"Updated House: {addr.get('house')}")
    except Exception as e:
        record("TC-ADDR-03", "Address", "Update Existing Customer Address", False, str(e))

    # 10.4 List Customer Addresses
    try:
        r = requests.get(f"{BASE_URL}/customer/addresses", headers=headers)
        addrs = r.json().get("data", {}).get("addresses", [])
        passed = r.status_code == 200 and len(addrs) > 0
        record("TC-ADDR-04", "Address", "List Saved Customer Addresses", passed, f"Count: {len(addrs)}")
    except Exception as e:
        record("TC-ADDR-04", "Address", "List Saved Customer Addresses", False, str(e))

    # 10.5 Delete Address
    try:
        r = requests.delete(f"{BASE_URL}/customer/addresses/{addr_id}", headers=headers)
        passed = r.status_code == 200 and r.json().get("success") == True
        record("TC-ADDR-05", "Address", "Delete Customer Address", passed, f"Status: {r.status_code}")
    except Exception as e:
        record("TC-ADDR-05", "Address", "Delete Customer Address", False, str(e))

    # 11. CUSTOMER BRANCHES MODULE
    try:
        r = requests.get(f"{BASE_URL}/customer/branches", headers=headers)
        branches = r.json().get("data", {}).get("branches", [])
        passed = r.status_code == 200 and len(branches) >= 2
        record("TC-BRN-01", "Branches", "List Store Tenant Active Branches", passed, f"Branches count: {len(branches)}")
    except Exception as e:
        record("TC-BRN-01", "Branches", "List Store Tenant Active Branches", False, str(e))

    # 12. LOGOUT MODULE
    try:
        payload = {"refresh_token": cust_refresh_token, "all_devices": False}
        r = requests.post(f"{BASE_URL}/auth/logout", json=payload, headers=headers)
        passed = r.status_code == 200 and r.json().get("success") == True
        record("TC-LOGOUT-01", "Logout", "User Logout & Refresh Token Revocation", passed, f"Status: {r.status_code}")
    except Exception as e:
        record("TC-LOGOUT-01", "Logout", "User Logout & Refresh Token Revocation", False, str(e))

    # SUMMARY REPORT
    total = len(results)
    passed_cnt = sum(1 for res in results if res["passed"])
    failed_cnt = total - passed_cnt
    print("\n=========================================================")
    print(f"      QA EXECUTION SUMMARY: {passed_cnt}/{total} PASSED")
    print("=========================================================")

if __name__ == "__main__":
    run_qa_suite()
