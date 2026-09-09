import requests

# End-to-end smoke test for POST /review.
# The API expects {"task": "<plain-language description>"}, NOT {"diff": ...}.
response = requests.post(
    "http://localhost:8000/review",
    json={"task": "Build a simple Spring Boot REST API for managing books (title, author) with CRUD endpoints, plus a React page listing books."},
    timeout=590,
)

print(response.status_code)
data = response.json()
print("id:", data.get("id"))
print("test_passed:", data.get("test_passed"))
print("requirements_met:", data.get("requirements_met"))
print("review_passed:", data.get("review_passed"))
print("revision_count:", data.get("revision_count"))
print("verified_findings:", len(data.get("verified_findings") or []))
print("steps:")
for step in data.get("steps_log") or []:
    print(" -", step)
