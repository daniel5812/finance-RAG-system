import httpx
import time
import os

API_URL = "http://localhost:8000"
DOCS = [
    "mock_quarterly_report_2026.txt",
    "mock_risk_strategy_2026.txt"
]

def upload_docs():
    headers = {"X-Owner-Id": "test_advisor_user"}
    for doc in DOCS:
        file_path = os.path.join(os.getcwd(), doc)
        with open(file_path, "rb") as f:
            files = {"file": (doc, f, "text/plain")}
            resp = httpx.post(f"{API_URL}/documents/upload", headers=headers, files=files)
            if resp.status_code == 202:
                print(f"Uploaded {doc}: {resp.json()['document_id']}")
            else:
                print(f"Failed to upload {doc}: {resp.status_code} {resp.text}")

if __name__ == "__main__":
    # Wait a bit for API to be ready
    print("Waiting for API to be healthy...")
    time.sleep(45) 
    upload_docs()
    print("Waiting for worker to index...")
    time.sleep(15) 
