import asyncio
import os
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["OPENAI_API_KEY"] = ""

from tests.conftest import onboard, run_interview
from fastapi.testclient import TestClient
from api.main import app

def check():
    with TestClient(app) as client:
        body = onboard(client)
        run_interview(client, body["session_id"])
        graph = client.get(f"/api/recruiter/candidates/{body['candidate_id']}").json()
        for claim in graph["claims"]:
            print(f"Claim: {claim['claim_type']}, score: {claim['claim_score']}")
            for dim in claim["dimensions"]:
                print(f"  Dim: {dim['dimension']}, score: {dim['score']}, signals: {dim['signal_count']}")
                print(f"    Basis: {dim['basis']}")

if __name__ == "__main__":
    check()
