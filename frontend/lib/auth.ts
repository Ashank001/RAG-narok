/**
 * lib/auth.ts
 * -----------
 * Utilities for managing the GitHub OAuth flow and JWT token lifecycle.
 * The token is stored in localStorage (client-only) and can be read
 * synchronously from anywhere in the browser environment.
 */

const TOKEN_KEY = "ragnarok_access_token";
const USERNAME_KEY = "ragnarok_username";

// ---------------------------------------------------------------------------
// Token storage helpers
// ---------------------------------------------------------------------------

/** Persist the JWT returned by the FastAPI backend. */
export function saveAuthToken(token: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(TOKEN_KEY, token);
}

/** Retrieve the stored JWT. Returns null if not logged in. */
export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

/** Clear the stored JWT (logout). */
export function clearAuthToken(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USERNAME_KEY);
}

/** Return true when a valid, non-expired token is present in storage. */
export function isAuthenticated(): boolean {
  const token = getAuthToken();
  if (!token) return false;

  // Decode the JWT payload (base64url middle segment) without a library.
  // We only need to check the `exp` claim — we are NOT verifying the signature
  // here (that happens server-side). This prevents expired-token silent 401s.
  try {
    const payloadBase64 = token.split(".")[1];
    if (!payloadBase64) return false;
    // base64url → base64 → JSON
    const json = atob(payloadBase64.replace(/-/g, "+").replace(/_/g, "/"));
    const { exp } = JSON.parse(json) as { exp?: number };
    if (exp && Date.now() / 1000 > exp) {
      // Token has expired — clean up storage
      clearAuthToken();
      return false;
    }
    return true;
  } catch {
    // Malformed token — treat as not authenticated
    clearAuthToken();
    return false;
  }
}

// ---------------------------------------------------------------------------
// Username helpers
// ---------------------------------------------------------------------------

export function saveUsername(username: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(USERNAME_KEY, username);
}

export function getUsername(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(USERNAME_KEY);
}

// ---------------------------------------------------------------------------
// GitHub OAuth redirect URL
// ---------------------------------------------------------------------------

/**
 * Builds the GitHub OAuth authorization URL.
 * Requires NEXT_PUBLIC_GITHUB_CLIENT_ID to be set in .env.local.
 *
 * GitHub docs: https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps
 */
export function buildGitHubOAuthUrl(): string {
  const clientId = process.env.NEXT_PUBLIC_GITHUB_CLIENT_ID;
  if (!clientId) {
    throw new Error(
      "NEXT_PUBLIC_GITHUB_CLIENT_ID is not set. Add it to your .env.local file."
    );
  }

  // Do NOT send redirect_uri — GitHub will use the one registered in your
  // OAuth App settings. Sending a value that doesn't match exactly (even a
  // trailing slash difference) triggers the "redirect_uri not associated" error.
  const params = new URLSearchParams({
    client_id: clientId,
    scope: "read:user user:email",
  });

  return `https://github.com/login/oauth/authorize?${params.toString()}`;
}
