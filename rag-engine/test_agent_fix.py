import os
import asyncio
import logging
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)

from agent import CodingAgent

async def run():
    print("Testing Agent execution...")
    agent = CodingAgent(
        task='Add a /health endpoint to the application that returns a JSON response with { "status": "ok" }.',
        repo_url="https://github.com/Ashank001/Flagent",
        session_id="test-400-session-fixed",  # the one we just ingested
        github_token="fake_token_for_test"
    )
    
    try:
        async for event in agent.execute():
            print(event)
            if "IMPLEMENTATION_PLAN" in event:
                print("SUCCESS: Context retrieved and reranker was skipped!")
                break
    except Exception as e:
        print(f"FAILED: {e}")

if __name__ == "__main__":
    asyncio.run(run())
