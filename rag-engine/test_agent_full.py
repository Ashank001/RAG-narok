import os
import asyncio
import logging
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)

from agent import CodingAgent

async def run():
    print("Testing Agent execution...")
    # Attempt to load a real token if available for testing, otherwise use a fallback
    token = os.getenv("GITHUB_TOKEN", os.getenv("OAUTH_SECRET_KEY", "fake_token_for_test"))
    
    agent = CodingAgent(
        task='Add a /health endpoint to the application that returns a JSON response with { "status": "ok" }. Follow the existing project structure and coding conventions. Run the existing tests after making the change. If the tests pass, commit the changes to a new feature branch and create a Pull Request against the default branch.',
        repo_url="https://github.com/Ashank001/Flagent",
        session_id="test-400-session-fixed",
        github_token=token
    )
    
    try:
        async for event in agent.execute():
            print(event)
    except Exception as e:
        print(f"FAILED: {e}")

if __name__ == "__main__":
    asyncio.run(run())
