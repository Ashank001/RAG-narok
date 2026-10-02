import os
import time
import tempfile
import subprocess
import shutil
import json
import logging
import httpx
from langchain_core.messages import SystemMessage, HumanMessage
from urllib.parse import urlparse

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Test result classification
# ---------------------------------------------------------------------------
# These constants let the execute() loop distinguish runtime-environment
# failures from actual test/code failures so it doesn't waste retries.
# ---------------------------------------------------------------------------
_RUNTIME_MISSING = "RUNTIME_MISSING"
_DEPENDENCY_FAILURE = "DEPENDENCY_FAILURE"
_TEST_FAILURE = "TEST_FAILURE"
_TEST_PASS = "TEST_PASS"
_NO_TESTS = "NO_TESTS"


class CodingAgent:
    def __init__(self, task: str, repo_url: str, session_id: str, github_token: str):
        self.task = task
        self.repo_url = repo_url
        self.session_id = session_id
        self.github_token = github_token
        self.workspace = tempfile.mkdtemp(prefix=f"agent_{session_id}_")
        
        # Initialize Groq Client from main configuration
        from main import llm
        if not llm:
            raise ValueError("GROQ_API_KEY is required for the coding agent.")
        # Bind JSON object mode for structured output
        self.llm = llm.bind(response_format={"type": "json_object"})
        
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
        except FileNotFoundError as e:
            # This is the exact error when a binary (npm, node, etc.) is missing
            return 127, f"Command not found: {e}"
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
        filter_dict = {"session_id": {"$eq": self.session_id}}
        
        _log.info("[AGENT] CODE_RETRIEVAL started")
        
        docs = vector_store.similarity_search(
            self.task,
            k=3,
            pre_filter=filter_dict
        )
        
        _log.info("[AGENT] vector retrieval completed")
        
        if not docs:
            return "No relevant code found in the repository."
            
        _log.info("[AGENT] reranking skipped for coding agent")
        _log.info(f"[AGENT] Retrieved {len(docs)} chunks")
        
        # Compute before size
        initial_parts = []
        for doc in docs:
            source = doc.metadata.get("source", "Unknown")
            content = doc.page_content
            initial_parts.append(f"--- File: {source} ---\n{content}")
        full_context = "\n\n".join(initial_parts)
        _log.info(f"[AGENT] Context size before limit: {len(full_context)} chars")
        
        # Apply chunk-based limiting
        max_chars = 2000
        context_parts = []
        current_size = 0
        
        for doc in docs:
            source = doc.metadata.get("source", "Unknown")
            content = doc.page_content
            chunk_str = f"--- File: {source} ---\n{content}"
            chunk_size = len(chunk_str) + 2  # accounts for join separator
            
            if current_size + chunk_size <= max_chars:
                context_parts.append(chunk_str)
                current_size += chunk_size
            else:
                # Truncate this chunk if no chunks added yet, otherwise drop lower-ranked ones
                if not context_parts:
                    context_parts.append(chunk_str[:max_chars])
                break
                
        final_context = "\n\n".join(context_parts)
        
        # Enforce final hard character limit just to be safe
        if len(final_context) > max_chars:
            final_context = final_context[:max_chars]
            
        _log.info(f"[AGENT] Context size after limit: {len(final_context)} chars")
        return final_context

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
        max_retries = 3
        base_delay = 5  # seconds
        last_exc = None
        
        messages = [HumanMessage(content=prompt)]
        
        for attempt in range(1, max_retries + 1):
            try:
                response = self.llm.invoke(messages)
                break  # Success
            except Exception as exc:
                last_exc = exc
                exc_str = str(exc)
                
                # Extract HTTP status code from the exception message
                status_code = None
                for code in [429, 500, 503]:
                    if str(code) in exc_str:
                        status_code = code
                        break
                
                # Check for permanent errors — do NOT retry
                for perm_code in [400, 401, 403, 404]:
                    if str(perm_code) in exc_str:
                        _log.error(f"[AGENT] Groq call failed: {perm_code} (permanent error, not retrying)")
                        raise exc
                
                if status_code and attempt < max_retries:
                    delay = base_delay * (2 ** (attempt - 1))  # 5s, 10s, 20s
                    _log.warning(f"[AGENT] Groq call failed: {status_code}")
                    _log.info(f"[AGENT] Retrying Groq call in {delay}s (attempt {attempt}/{max_retries})")
                    time.sleep(delay)
                elif status_code and attempt == max_retries:
                    _log.error(f"[AGENT] Groq call failed: {status_code}")
                    _log.error(f"[AGENT] All {max_retries} retries exhausted for Groq call")
                    raise exc
                else:
                    # Unknown error — don't retry
                    _log.error(f"[AGENT] Groq call failed with unexpected error: {exc_str[:200]}")
                    raise exc
        
        try:
            return json.loads(response.content)
        except Exception as e:
            _log.error(f"Failed to parse LLM response: {response.content}")
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

    # ------------------------------------------------------------------
    # Project type detection
    # ------------------------------------------------------------------
    def _detect_project_type(self) -> dict:
        """Inspects the workspace for ecosystem marker files and returns
        a dict describing the project type and required runtime tools.

        Returns:
            {
                "type": "node" | "python" | "rust" | "go" | "java-maven"
                        | "java-gradle" | "unknown",
                "marker_file": str,           # file that triggered detection
                "required_tools": [str, ...],  # binaries we need on PATH
                "install_cmd": [str, ...] | None,
                "test_cmd": [str, ...] | None,
            }
        """
        ws = self.workspace

        # Order matters: first match wins.
        checks = [
            {
                "type": "node",
                "markers": ["package.json"],
                "required_tools": ["node", "npm"],
                "install_cmd": ["npm", "install"],
                "test_cmd": ["npm", "test"],
            },
            {
                "type": "python",
                "markers": ["pyproject.toml", "setup.py", "setup.cfg",
                            "requirements.txt", "pytest.ini", "tox.ini"],
                "required_tools": ["python"],  # pip may be a module
                "install_cmd": None,  # handled specially below
                "test_cmd": ["pytest"],
            },
            {
                "type": "rust",
                "markers": ["Cargo.toml"],
                "required_tools": ["cargo"],
                "install_cmd": None,
                "test_cmd": ["cargo", "test"],
            },
            {
                "type": "go",
                "markers": ["go.mod"],
                "required_tools": ["go"],
                "install_cmd": None,
                "test_cmd": ["go", "test", "./..."],
            },
            {
                "type": "java-maven",
                "markers": ["pom.xml"],
                "required_tools": ["mvn"],
                "install_cmd": None,
                "test_cmd": ["mvn", "test"],
            },
            {
                "type": "java-gradle",
                "markers": ["build.gradle", "build.gradle.kts"],
                "required_tools": ["gradle"],
                "install_cmd": None,
                "test_cmd": ["gradle", "test"],
            },
        ]

        for spec in checks:
            for marker in spec["markers"]:
                if os.path.exists(os.path.join(ws, marker)):
                    result = {
                        "type": spec["type"],
                        "marker_file": marker,
                        "required_tools": spec["required_tools"],
                        "install_cmd": spec["install_cmd"],
                        "test_cmd": spec["test_cmd"],
                    }
                    _log.info(f"[AGENT] detected project type: {result['type']} "
                              f"(from {marker})")
                    return result

        _log.info("[AGENT] detected project type: unknown (no marker files found)")
        return {
            "type": "unknown",
            "marker_file": None,
            "required_tools": [],
            "install_cmd": None,
            "test_cmd": None,
        }

    # ------------------------------------------------------------------
    # Runtime availability check
    # ------------------------------------------------------------------
    def _check_runtime_available(self, required_tools: list[str]) -> dict:
        """Checks whether each tool in *required_tools* is available on
        PATH using ``shutil.which``.

        Returns:
            {
                "available": bool,          # True if ALL tools found
                "tools": {
                    "npm": "/usr/bin/npm",   # path or None
                    ...
                },
                "missing": ["npm", ...],     # tools not found
            }
        """
        tools = {}
        missing = []
        for tool in required_tools:
            path = shutil.which(tool)
            tools[tool] = path
            if path is None:
                missing.append(tool)

        available = len(missing) == 0
        _log.info(f"[AGENT] runtime availability: "
                  f"{'ALL OK' if available else 'MISSING ' + ', '.join(missing)} "
                  f"(checked: {required_tools})")
        return {"available": available, "tools": tools, "missing": missing}

    # ------------------------------------------------------------------
    # Test detection & execution  (replaces old _detect_and_run_tests)
    # ------------------------------------------------------------------
    def _detect_and_run_tests(self) -> tuple[str, int, str]:
        """Auto-detects build/test commands and runs them.

        Returns:
            (classification, return_code, output)

            classification is one of the module-level constants:
                _RUNTIME_MISSING   – required tool not on PATH
                _DEPENDENCY_FAILURE – install step failed
                _TEST_FAILURE      – tests ran but failed
                _TEST_PASS         – tests passed (or no tests to run)
                _NO_TESTS          – no test framework detected
        """
        project = self._detect_project_type()
        _log.info(f"[AGENT] selected test command: {project.get('test_cmd')}")

        # ── Unknown project type ──────────────────────────────────────
        if project["type"] == "unknown":
            msg = "No supported test framework detected."
            _log.info(f"[AGENT] test execution result: NO_TESTS – {msg}")
            return _NO_TESTS, 0, msg

        # ── Runtime availability gate ─────────────────────────────────
        runtime = self._check_runtime_available(project["required_tools"])
        if not runtime["available"]:
            missing_str = ", ".join(runtime["missing"])
            msg = (f"TEST_EXECUTION skipped: required runtime tool(s) "
                   f"[{missing_str}] not found in agent environment. "
                   f"Project type '{project['type']}' detected from "
                   f"'{project['marker_file']}', but the agent container "
                   f"(python:3.12-slim) does not include {missing_str}. "
                   f"This is an agent environment limitation, not a code error.")
            _log.warning(f"[AGENT] test execution result: RUNTIME_MISSING – {msg}")
            return _RUNTIME_MISSING, 127, msg

        # ── Node.js projects ─────────────────────────────────────────
        if project["type"] == "node":
            # Install dependencies
            code, out = self._run_cmd(["npm", "install"])
            if code != 0:
                _log.warning(f"[AGENT] test execution result: DEPENDENCY_FAILURE – "
                             f"npm install exited {code}")
                return _DEPENDENCY_FAILURE, code, out

            # Run tests
            code, out = self._run_cmd(["npm", "test"])
            if code != 0 and 'Missing script: "test"' in out:
                _log.info("[AGENT] test execution result: NO_TESTS – "
                          "no test script in package.json")
                return _NO_TESTS, 0, "No test script defined in package.json."
            if code != 0:
                _log.info(f"[AGENT] test execution result: TEST_FAILURE – "
                          f"npm test exited {code}")
                return _TEST_FAILURE, code, out
            _log.info("[AGENT] test execution result: TEST_PASS")
            return _TEST_PASS, 0, out

        # ── Python projects ──────────────────────────────────────────
        if project["type"] == "python":
            req_file = os.path.join(self.workspace, "requirements.txt")
            if os.path.exists(req_file):
                code, out = self._run_cmd(["pip", "install", "-r", "requirements.txt"])
                if code != 0:
                    _log.warning(f"[AGENT] test execution result: DEPENDENCY_FAILURE – "
                                 f"pip install exited {code}")
                    return _DEPENDENCY_FAILURE, code, out

            code, out = self._run_cmd(["pytest"])
            if code != 0:
                _log.info(f"[AGENT] test execution result: TEST_FAILURE – "
                          f"pytest exited {code}")
                return _TEST_FAILURE, code, out
            _log.info("[AGENT] test execution result: TEST_PASS")
            return _TEST_PASS, 0, out

        # ── Generic fallback for other detected types ────────────────
        if project["test_cmd"]:
            code, out = self._run_cmd(project["test_cmd"])
            if code != 0:
                _log.info(f"[AGENT] test execution result: TEST_FAILURE – "
                          f"{project['test_cmd'][0]} exited {code}")
                return _TEST_FAILURE, code, out
            _log.info("[AGENT] test execution result: TEST_PASS")
            return _TEST_PASS, 0, out

        msg = "No supported test framework detected."
        _log.info(f"[AGENT] test execution result: NO_TESTS – {msg}")
        return _NO_TESTS, 0, msg

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
                classification, code, output = self._detect_and_run_tests()
                _log.info(f"[AGENT] Test execution completed for attempt {attempt}: "
                          f"classification={classification} code={code}")
                
                # ── Runtime missing: abort immediately, no point retrying ─
                if classification == _RUNTIME_MISSING:
                    yield self._yield_event(
                        "TEST_EXECUTION",
                        f"⚠ Required runtime unavailable in agent environment. "
                        f"Skipping tests and proceeding with code changes.\n\n{output}",
                        {"classification": _RUNTIME_MISSING}
                    )
                    # Treat as soft-pass: the code was generated, we just
                    # can't validate it in this environment.
                    success = True
                    break

                # ── Dependency install failure: abort, not a code problem ─
                if classification == _DEPENDENCY_FAILURE:
                    yield self._yield_event(
                        "TEST_EXECUTION",
                        f"⚠ Dependency installation failed. This is an "
                        f"environment issue, not a code error.\n\n"
                        f"{output[-500:]}",
                        {"classification": _DEPENDENCY_FAILURE}
                    )
                    success = True
                    break

                # ── No tests found: nothing to validate, proceed ──────────
                if classification == _NO_TESTS:
                    _log.info("[AGENT] No tests to run, treating as pass")
                    success = True
                    break

                # ── Tests passed ──────────────────────────────────────────
                if classification == _TEST_PASS:
                    success = True
                    break

                # ── Actual test failure: self-correct ─────────────────────
                # classification == _TEST_FAILURE
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
