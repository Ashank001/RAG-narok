import os
import shutil
import asyncio
from agent import CodingAgent

async def run():
    # 1. Create a tiny local git repo
    repo_dir = os.path.abspath('tiny_repo')
    if os.path.exists(repo_dir):
        shutil.rmtree(repo_dir)
    os.makedirs(repo_dir)
    os.system(f'cd {repo_dir} && git init && echo def dummy(): pass > app.py && git add . && git commit -m "Init"')

    # Mock the clone to just copy the local repo
    original_clone = CodingAgent._clone_repo
    def mock_clone(self):
        os.system(f'xcopy /E /I {repo_dir} {self.workspace}')
        self._run_cmd(['git', 'config', 'user.name', 'Test'])
        self._run_cmd(['git', 'config', 'user.email', 'test@test.com'])
        branch_name = f'feature-{self.session_id}'
        self._run_cmd(['git', 'checkout', '-b', branch_name])
        return branch_name
    CodingAgent._clone_repo = mock_clone
    
    # Mock push and PR
    def mock_run_cmd(self, cmd, cwd=None):
        if 'push' in cmd:
            print('MOCK: git push')
            return 0, 'mock push success'
        return CodingAgent._original_run_cmd(self, cmd, cwd)
    
    CodingAgent._original_run_cmd = CodingAgent._run_cmd
    CodingAgent._run_cmd = mock_run_cmd
    
    def mock_pr(self, branch):
        print('MOCK: create PR')
        return 'https://github.com/mock/repo/pull/1'
    CodingAgent._create_pull_request = mock_pr

    agent = CodingAgent(
        task='Add a /health endpoint that returns HTTP 200 and a JSON response containing {"status":"ok"}. Modify app.py.',
        repo_url='https://github.com/mock/repo',
        session_id='test-123',
        github_token='mock'
    )
    
    async for event in agent.execute():
        print(event)

if __name__ == '__main__':
    asyncio.run(run())
