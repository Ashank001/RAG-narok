import os
import tempfile
import subprocess
import json
import logging
import httpx
import google.genai as genai
from urllib.parse import urlparse

_log = logging.getLogger(__name__)

class CodingAgent:
    def __init__(self, task: str, repo_url: str, session_id: str, github_token: str):
        self.task = task
        self.repo_url = repo_url
        self.session_id = session_id
        self.github_token = github_token
        self.workspace = tempfile.mkdtemp(prefix=f"agent_{session_id}_")
        
        # Initialize Gemini Client
        gemini_api_key = os.getenv("GEMINI_API_KEY")
        if not gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required for the coding agent.")
        self.client = genai.Client(api_key=gemini_api_key)
        
        # Parse owner and repo from URL
        parsed = urlparse(repo_url)
        path_parts = parsed.path.strip("/").split("/")
        if len(path_parts) >= 2:
            self.repo_owner = path_parts[0]
            self.repo_name = path_parts[1].replace(".git", "")
        else:
            raise ValueError("Invalid GitHub repository URL")

    def _yield_event(self, stage: str, message: str, data: dict = None):
        """Helper to format SSE events."""
        payload = {"stage": stage, "message": message}
        if data:
            payload.update(data)
        _log.info(f"[AGENT] {stage}: {message}")
        return f"data: {json.dumps(payload)}\n\n"

    def _run_cmd(self, cmd: list, cwd: str = None) -> tuple[int, str]:
        """Runs a shell command safely in the workspace and returns (returncode, output)."""
        if not cwd:
            cwd = self.workspace
            
        # Prevent git from prompting for credentials in the terminal
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_ASKPASS"] = "echo"
        
        try:
            _log.info(f"[AGENT] Running command: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=60
            )
            output = result.stdout + "\n" + result.stderr
            return result.returncode, output
        except subprocess.TimeoutExpired:
            return 124, "Command timed out after 60 seconds."
        except Exception as e:
            return 1, str(e)

    def _clone_repo(self):
        """Clones the repository using the user's GitHub token."""
        _log.info(f"[AGENT] Cloning repository {self.repo_url}")
        auth_url = self.repo_url.replace("https://", f"https://oauth2:{self.github_token}@")
        code, out = self._run_cmd(["git", "clone", auth_url, "."])
        if code != 0:
            raise RuntimeError(f"Failed to clone repository: {out}")
            
        self._run_cmd(["git", "config", "user.name", "RAGnarok Autonomous Agent"])
        self._run_cmd(["git", "config", "user.email", "agent@ragnarok.local"])
        branch_name = f"ragnarok-feature-{self.session_id[:8]}"
        code, out = self._run_cmd(["git", "checkout", "-b", branch_name])
        if code != 0:
            raise RuntimeError(f"Failed to create branch: {out}")
        return branch_name

    def _get_code_context(self):
        """Retrieves relevant code context using the existing vector store."""
        from main import get_vector_store, RETRIEVAL_TOP_K
        
        vector_store = get_vector_store()
        
        # Pre-filter by session ID
        filter_dict = {"session_id": self.session_id}
        
        _log.info("[AGENT] CODE_RETRIEVAL started")
        
        docs = vector_store.similarity_search(
            self.task,
            k=RETRIEVAL_TOP_K,
            pre_filter=filter_dict
        )
        
        _log.info("[AGENT] vector retrieval completed")
        
        if not docs:
            return "No relevant code found in the repository."
            
        _log.info("[AGENT] reranking skipped for coding agent")
        
        context_parts = []
        for doc in docs:
            source = doc.metadata.get("source", "Unknown")
            content = doc.page_content
            context_parts.append(f"--- File: {source} ---\n{content}")
            
        _log.info("[AGENT] context ready")
        return "\n\n".join(context_parts)

    def _generate_edits(self, context: str, error_feedback: str = None):
        """Uses LLM to generate file modifications."""
        prompt = f"""You are an expert autonomous coding agent.
Your task is to implement the following feature request: {self.task}

Relevant codebase context:
{context}

"""
        if error_feedback:
            prompt += f"""
PREVIOUS ATTEMPT FAILED WITH ERROR:
{error_feedback}
Please fix the issue in your new modifications.
"""

        prompt += """
Return your response ONLY as a valid JSON object matching this schema. Do NOT include markdown code blocks around the JSON.
{
    "modifications": [
        {
            "file_path": "path/to/file.py",
            "content": "the complete new content for this file"
        }
    ]
}
"""
        response = self.client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2
            )
        )
        
        try:
            return json.loads(response.text)
        except Exception as e:
            _log.error(f"Failed to parse LLM response: {response.text}")
            raise ValueError("LLM returned invalid JSON.")

    def _apply_edits(self, edits: dict):
        """Applies the LLM modifications to the workspace."""
        for mod in edits.get("modifications", []):
            file_path = mod.get("file_path")
            content = mod.get("content")
            
            # Security: Prevent traversing outside workspace
            safe_path = os.path.abspath(os.path.join(self.workspace, file_path))
            if not safe_path.startswith(os.path.abspath(self.workspace)):
                _log.warning(f"Blocked attempt to modify outside workspace: {file_path}")
                continue
                
            os.makedirs(os.path.dirname(safe_path), exist_ok=True)
            with open(safe_path, "w", encoding="utf-8") as f:
                f.write(content)

    def _detect_and_run_tests(self):
        """Auto-detects build/test commands and runs them."""
        # Node.js
        if os.path.exists(os.path.join(self.workspace, "package.json")):
            code, out = self._run_cmd(["npm", "install"])
            if code != 0: return code, out
            
            code, out = self._run_cmd(["npm", "test"])
            # If no test script, npm test returns non-zero, but we can check output
            if code != 0 and "Missing script: \"test\"" in out:
                return 0, "No tests found."
            return code, out
            
        # Python
        if os.path.exists(os.path.join(self.workspace, "pytest.ini")) or \
           os.path.exists(os.path.join(self.workspace, "requirements.txt")):
            if os.path.exists(os.path.join(self.workspace, "requirements.txt")):
                self._run_cmd(["pip", "install", "-r", "requirements.txt"])
            return self._run_cmd(["pytest"])
            
        return 0, "No supported test framework detected."

    def _create_pull_request(self, branch_name: str):
        """Creates a PR via GitHub API."""
        url = f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}/pulls"
        headers = {
            "Authorization": f"Bearer {self.github_token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        payload = {
            "title": f"Agent: {self.task[:50]}...",
            "body": f"Automated PR by RAGnarok Agent.\n\nTask: {self.task}",
            "head": branch_name,
            "base": "main"  # Assuming main, but GitHub API will fallback or fail if not
        }
        
        # Some repos use 'master', let's fetch default branch first
        repo_info_resp = httpx.get(f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}", headers=headers, timeout=30.0)
        if repo_info_resp.status_code == 200:
            payload["base"] = repo_info_resp.json().get("default_branch", "main")

        resp = httpx.post(url, headers=headers, json=payload, timeout=30.0)
        resp.raise_for_status()
        return resp.json().get("html_url")

    async def execute(self):
        """Main execution workflow, yields SSE events."""
        _log.info(f"[AGENT] Task execution started for session {self.session_id}")
        try:
            yield self._yield_event("CODE_RETRIEVAL", "Analyzing task and retrieving code context...")
            context = self._get_code_context()
            
            _log.info("[AGENT] IMPLEMENTATION_PLAN started")
            yield self._yield_event("IMPLEMENTATION_PLAN", "Cloning repository and planning modifications...")
            branch_name = self._clone_repo()
            _log.info(f"[AGENT] Workspace initialized and branch {branch_name} created")
            
            error_feedback = None
            success = False
            
            # Max 3 attempts
            for attempt in range(1, 4):
                _log.info(f"[AGENT] Generation attempt {attempt}/3 started")
                yield self._yield_event("CODE_MODIFICATION", f"Generating and applying code changes (Attempt {attempt}/3)...")
                edits = self._generate_edits(context, error_feedback)
                self._apply_edits(edits)
                _log.info(f"[AGENT] Code modification applied for attempt {attempt}")
                
                yield self._yield_event("TEST_EXECUTION", f"Running tests (Attempt {attempt}/3)...")
                code, output = self._detect_and_run_tests()
                _log.info(f"[AGENT] Test execution completed for attempt {attempt} with code {code}")
                
                if code == 0:
                    success = True
                    break
                else:
                    error_feedback = f"Test Execution Failed:\n{output[-2000:]}"  # last 2k chars
                    yield self._yield_event("FAILURE_ANALYSIS", f"Tests failed. Analyzing failure...\n{output[-500:]}")
            
            if not success:
                _log.info("[AGENT] Failed after 3 attempts")
                yield self._yield_event("ERROR", "Agent failed to implement the feature after 3 attempts.", {"details": error_feedback})
                return
                
            yield self._yield_event("GIT_COMMIT", "Changes successful. Committing and pushing...")
            code, out = self._run_cmd(["git", "add", "."])
            code, out = self._run_cmd(["git", "commit", "-m", f"Implement: {self.task}"])
            code, out = self._run_cmd(["git", "push", "-u", "origin", branch_name])
            if code != 0:
                raise RuntimeError(f"Failed to push branch: {out}")
            _log.info("[AGENT] Branch pushed to remote")
            
            yield self._yield_event("GITHUB_PR", "Creating Pull Request...")
            pr_url = self._create_pull_request(branch_name)
            _log.info(f"[AGENT] PR created successfully: {pr_url}")
            
            yield self._yield_event("COMPLETED", "Task completed successfully!", {"pr_url": pr_url})
            
        except Exception as e:
            _log.exception("[AGENT] Execution failed with exception")
            yield self._yield_event("ERROR", f"Agent execution failed: {str(e)}")
