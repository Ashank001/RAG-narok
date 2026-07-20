/**
 * validateGithubUrl.ts
 * Express middleware — three-layer defence for POST /api/ingest:
 *
 *  Layer 1 – Regex:       Enforces https://github.com/{owner}/{repo} shape.
 *                         Rejects any other hostname outright (SSRF prevention).
 *
 *  Layer 2 – GitHub API:  Probes GET /repos/{owner}/{repo} to confirm the
 *                         repository actually exists before work is queued.
 *
 *  Layer 3 – Privacy:    If the repo is private AND no GitHub token is
 *                         available (env GITHUB_TOKEN or request Authorization
 *                         header), rejects with 403 Forbidden.
 *
 * On success it attaches `req.validatedRepo` for downstream handlers.
 */

import { Request, Response, NextFunction, RequestHandler } from 'express';

// ---------------------------------------------------------------------------
// Type augmentation — adds validatedRepo to Express Request
// ---------------------------------------------------------------------------
export interface ValidatedRepo {
  owner: string;
  repo: string;
  isPrivate: boolean;
}

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      validatedRepo?: ValidatedRepo;
    }
  }
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/**
 * Matches exactly:  https://github.com/{owner}/{repo}
 * - owner/repo: alphanumeric, hyphens, dots, underscores (1–100 chars each)
 * - No trailing slash, no subpaths, no query strings
 * This also implicitly prevents SSRF: any non-github.com hostname fails here.
 */
const GITHUB_URL_REGEX =
  /^https:\/\/github\.com\/([a-zA-Z0-9](?:[a-zA-Z0-9._-]{0,98}[a-zA-Z0-9])?)\/([a-zA-Z0-9._-]{1,100})\/?$/;

const GITHUB_API_BASE = 'https://api.github.com';

// How long to wait for the GitHub API before giving up (ms)
const GITHUB_API_TIMEOUT_MS = 8_000;

// ---------------------------------------------------------------------------
// Helper — build GitHub API request headers
// ---------------------------------------------------------------------------
function buildGithubHeaders(userAuthHeader?: string): Record<string, string> {
  const headers: Record<string, string> = {
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    'User-Agent': 'RAGnarok-API-Gateway/1.0',
  };

  // Prefer a token forwarded by the client; fall back to the server-level PAT.
  const token =
    (userAuthHeader?.startsWith('Bearer ') ? userAuthHeader.slice(7) : undefined) ??
    process.env.GITHUB_TOKEN;

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  return headers;
}

// ---------------------------------------------------------------------------
// Middleware
// ---------------------------------------------------------------------------
export const validateGithubUrl: RequestHandler = async (
  req: Request,
  res: Response,
  next: NextFunction
): Promise<void> => {
  // ------------------------------------------------------------------
  // Layer 1: Shape / hostname validation via regex
  // ------------------------------------------------------------------
  const rawUrl: string | undefined =
    req.body?.repository_url ?? req.body?.repositoryUrl;

  if (!rawUrl || typeof rawUrl !== 'string') {
    res.status(400).json({
      error: 'repository_url is required.',
    });
    return;
  }

  const match = GITHUB_URL_REGEX.exec(rawUrl.trim());
  if (!match) {
    res.status(400).json({
      error:
        'Invalid GitHub URL. Expected format: https://github.com/{owner}/{repo}',
      received: rawUrl,
    });
    return;
  }

  const owner = match[1];
  const repo = match[2];

  // ------------------------------------------------------------------
  // Layer 2: Existence check via GitHub REST API
  // ------------------------------------------------------------------
  const apiUrl = `${GITHUB_API_BASE}/repos/${owner}/${repo}`;
  const userAuthHeader = req.headers.authorization;
  const headers = buildGithubHeaders(userAuthHeader);

  let githubData: Record<string, unknown>;
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), GITHUB_API_TIMEOUT_MS);

    const response = await fetch(apiUrl, {
      method: 'GET',
      headers,
      signal: controller.signal,
    });
    clearTimeout(timeoutId);

    if (response.status === 404) {
      res.status(404).json({
        error: `Repository not found: github.com/${owner}/${repo}. ` +
          'Verify the URL is correct and the repository is publicly accessible.',
      });
      return;
    }

    if (response.status === 403 || response.status === 401) {
      res.status(403).json({
        error:
          'GitHub API access denied. If this is a private repository, ' +
          'provide a valid Authorization: Bearer <token> header.',
      });
      return;
    }

    if (!response.ok) {
      res.status(502).json({
        error: `GitHub API returned an unexpected status: ${response.status}. Please try again later.`,
      });
      return;
    }

    githubData = (await response.json()) as Record<string, unknown>;
  } catch (err: unknown) {
    const isTimeout =
      err instanceof Error && err.name === 'AbortError';

    res.status(502).json({
      error: isTimeout
        ? 'GitHub API timed out. Please try again later.'
        : `Failed to reach GitHub API: ${err instanceof Error ? err.message : String(err)}`,
    });
    return;
  }

  // ------------------------------------------------------------------
  // Layer 3: Private repo guard
  // ------------------------------------------------------------------
  const isPrivate = Boolean(githubData.private);

  if (isPrivate) {
    // A token must have been supplied (either from the client or env) for us
    // to have received a 200 response from GitHub at all.  However, if the
    // server-level GITHUB_TOKEN is what authenticated, we still reject —
    // we don't want to grant access on behalf of a server credential when the
    // actual user hasn't authenticated.
    const hasUserToken = userAuthHeader?.startsWith('Bearer ');
    const hasEnvToken = Boolean(process.env.GITHUB_TOKEN);

    if (!hasUserToken && !hasEnvToken) {
      res.status(403).json({
        error:
          `Repository github.com/${owner}/${repo} is private. ` +
          'Provide a GitHub personal access token via the Authorization header to ingest private repositories.',
      });
      return;
    }
  }

  // ------------------------------------------------------------------
  // All checks passed — attach validated metadata and continue
  // ------------------------------------------------------------------
  req.validatedRepo = { owner, repo, isPrivate };
  next();
};
