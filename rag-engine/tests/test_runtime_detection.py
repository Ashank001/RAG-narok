"""
Tests for the agent's project detection and runtime availability logic.

Specifically validates the expressjs/express failure scenario:
  package.json exists → project detected as "node" → npm not on PATH →
  RUNTIME_MISSING returned immediately (no 3x retry of the same broken command).
"""
import os
import sys
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# Allow imports from the parent rag-engine directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Mock 'main' module before importing agent so the top-level import succeeds
mock_main = MagicMock()
mock_main.llm = MagicMock()
mock_main.get_vector_store = MagicMock()
mock_main.RETRIEVAL_TOP_K = 3
sys.modules["main"] = mock_main

from agent import (
    CodingAgent,
    _RUNTIME_MISSING,
    _DEPENDENCY_FAILURE,
    _TEST_FAILURE,
    _TEST_PASS,
    _NO_TESTS,
)


class _AgentWithWorkspace:
    """Helper to create a CodingAgent with a temp workspace without calling __init__."""

    def __enter__(self):
        self.workspace = tempfile.mkdtemp(prefix="test_agent_")
        # Build a minimal agent bypassing __init__ (avoids LLM/URL setup)
        agent = object.__new__(CodingAgent)
        agent.workspace = self.workspace
        self.agent = agent
        return agent

    def __exit__(self, *exc):
        shutil.rmtree(self.workspace, ignore_errors=True)


# ── Project type detection ───────────────────────────────────────────

class TestDetectProjectType(unittest.TestCase):
    """_detect_project_type should identify ecosystems from marker files."""

    def test_node_project(self):
        with _AgentWithWorkspace() as agent:
            # Simulate expressjs/express: has package.json
            with open(os.path.join(agent.workspace, "package.json"), "w") as f:
                json.dump({"name": "express", "scripts": {"test": "mocha"}}, f)

            result = agent._detect_project_type()
            self.assertEqual(result["type"], "node")
            self.assertEqual(result["marker_file"], "package.json")
            self.assertIn("npm", result["required_tools"])
            self.assertIn("node", result["required_tools"])

    def test_python_project_requirements(self):
        with _AgentWithWorkspace() as agent:
            open(os.path.join(agent.workspace, "requirements.txt"), "w").close()

            result = agent._detect_project_type()
            self.assertEqual(result["type"], "python")

    def test_python_project_pyproject(self):
        with _AgentWithWorkspace() as agent:
            open(os.path.join(agent.workspace, "pyproject.toml"), "w").close()

            result = agent._detect_project_type()
            self.assertEqual(result["type"], "python")

    def test_rust_project(self):
        with _AgentWithWorkspace() as agent:
            open(os.path.join(agent.workspace, "Cargo.toml"), "w").close()

            result = agent._detect_project_type()
            self.assertEqual(result["type"], "rust")

    def test_go_project(self):
        with _AgentWithWorkspace() as agent:
            open(os.path.join(agent.workspace, "go.mod"), "w").close()

            result = agent._detect_project_type()
            self.assertEqual(result["type"], "go")

    def test_unknown_project(self):
        with _AgentWithWorkspace() as agent:
            # Empty directory → unknown
            result = agent._detect_project_type()
            self.assertEqual(result["type"], "unknown")
            self.assertEqual(result["required_tools"], [])


# ── Runtime availability ─────────────────────────────────────────────

class TestCheckRuntimeAvailable(unittest.TestCase):
    """_check_runtime_available should report missing tools accurately."""

    def test_python_available(self):
        """Python should be available since we're running this test in Python."""
        with _AgentWithWorkspace() as agent:
            result = agent._check_runtime_available(["python"])
            # python (or python3) should be on PATH
            # On some systems 'python' may not exist but 'python3' does;
            # for this test we just check the structure is correct
            self.assertIn("available", result)
            self.assertIn("missing", result)
            self.assertIn("tools", result)

    def test_npm_missing_in_python_env(self):
        """Simulates the Render environment: npm is NOT installed."""
        with _AgentWithWorkspace() as agent:
            # Patch shutil.which to return None for node/npm
            with patch("shutil.which", side_effect=lambda t: None):
                result = agent._check_runtime_available(["node", "npm"])
                self.assertFalse(result["available"])
                self.assertIn("node", result["missing"])
                self.assertIn("npm", result["missing"])

    def test_all_tools_present(self):
        with _AgentWithWorkspace() as agent:
            with patch("shutil.which", return_value="/usr/bin/fake"):
                result = agent._check_runtime_available(["node", "npm"])
                self.assertTrue(result["available"])
                self.assertEqual(result["missing"], [])


# ── Full _detect_and_run_tests flow ──────────────────────────────────

class TestDetectAndRunTests(unittest.TestCase):
    """Integration-level tests of the combined detect → check → execute flow."""

    def test_express_repo_npm_missing(self):
        """The exact expressjs/express scenario: package.json present, npm absent.

        Expected: RUNTIME_MISSING returned on the first call, no subprocess
        invocation of npm at all.
        """
        with _AgentWithWorkspace() as agent:
            with open(os.path.join(agent.workspace, "package.json"), "w") as f:
                json.dump({"name": "express"}, f)

            # npm/node not on PATH
            with patch("shutil.which", return_value=None):
                classification, code, output = agent._detect_and_run_tests()

            self.assertEqual(classification, _RUNTIME_MISSING)
            self.assertEqual(code, 127)
            self.assertIn("node", output)
            self.assertIn("npm", output)
            self.assertIn("agent environment", output.lower())

    def test_express_repo_npm_missing_no_subprocess(self):
        """Ensure that when runtime is missing, subprocess is NEVER called."""
        with _AgentWithWorkspace() as agent:
            with open(os.path.join(agent.workspace, "package.json"), "w") as f:
                json.dump({"name": "express"}, f)

            with patch("shutil.which", return_value=None), \
                 patch.object(agent, "_run_cmd") as mock_run:
                agent._detect_and_run_tests()
                mock_run.assert_not_called()

    def test_unknown_project_returns_no_tests(self):
        with _AgentWithWorkspace() as agent:
            classification, code, output = agent._detect_and_run_tests()
            self.assertEqual(classification, _NO_TESTS)
            self.assertEqual(code, 0)

    def test_node_project_test_pass(self):
        """If npm is present and tests pass, should return TEST_PASS."""
        with _AgentWithWorkspace() as agent:
            with open(os.path.join(agent.workspace, "package.json"), "w") as f:
                json.dump({"name": "express"}, f)

            with patch("shutil.which", return_value="/usr/bin/npm"), \
                 patch.object(agent, "_run_cmd", return_value=(0, "all tests passed")):
                classification, code, output = agent._detect_and_run_tests()

            self.assertEqual(classification, _TEST_PASS)
            self.assertEqual(code, 0)

    def test_node_project_npm_install_fails(self):
        """npm install failure → DEPENDENCY_FAILURE, not TEST_FAILURE."""
        with _AgentWithWorkspace() as agent:
            with open(os.path.join(agent.workspace, "package.json"), "w") as f:
                json.dump({"name": "express"}, f)

            with patch("shutil.which", return_value="/usr/bin/npm"), \
                 patch.object(agent, "_run_cmd", return_value=(1, "ENOMEM")):
                classification, code, output = agent._detect_and_run_tests()

            self.assertEqual(classification, _DEPENDENCY_FAILURE)

    def test_node_project_test_failure(self):
        """Actual test failure → TEST_FAILURE (should trigger self-correction)."""
        with _AgentWithWorkspace() as agent:
            with open(os.path.join(agent.workspace, "package.json"), "w") as f:
                json.dump({"name": "express"}, f)

            call_count = [0]
            def mock_run(cmd, cwd=None):
                call_count[0] += 1
                if call_count[0] == 1:
                    return 0, "npm install ok"  # install succeeds
                return 1, "AssertionError: expected 200 got 500"  # test fails

            with patch("shutil.which", return_value="/usr/bin/npm"), \
                 patch.object(agent, "_run_cmd", side_effect=mock_run):
                classification, code, output = agent._detect_and_run_tests()

            self.assertEqual(classification, _TEST_FAILURE)
            self.assertIn("AssertionError", output)


if __name__ == "__main__":
    unittest.main()
