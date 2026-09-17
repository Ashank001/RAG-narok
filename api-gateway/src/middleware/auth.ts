/**
 * middleware/auth.ts
 * ------------------
 * JWT verification middleware for the API Gateway.
 *
 * Uses the same JWT_SECRET_KEY and HS256 algorithm as the FastAPI backend
 * so tokens issued by FastAPI are valid here and vice versa.
 *
 * On success, attaches `req.user = { githubUsername }` to the request.
 * On failure, returns 401 Unauthorized.
 *
 * Also supports the X-Internal-Key header for service-to-service calls
 * (e.g., from the BullMQ ingestion worker).
 */

import { Request, Response, NextFunction, RequestHandler } from 'express';
import jwt from 'jsonwebtoken';

// ---------------------------------------------------------------------------
// Type augmentation — adds user to Express Request
// ---------------------------------------------------------------------------
export interface AuthUser {
  githubUsername: string;
}

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      user?: AuthUser;
    }
  }
}

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------
const JWT_SECRET = process.env.JWT_SECRET_KEY || '';
const JWT_ALGORITHM = 'HS256';
const INTERNAL_API_KEY = process.env.INTERNAL_API_KEY || '';

if (!JWT_SECRET) {
  console.warn('[Auth Middleware] ⚠️ JWT_SECRET_KEY not set — auth will reject all tokens');
}

// ---------------------------------------------------------------------------
// Middleware
// ---------------------------------------------------------------------------
export const requireAuth: RequestHandler = (
  req: Request,
  res: Response,
  next: NextFunction
): void => {
  // ── Internal service-to-service bypass ──
  const internalKey = req.headers['x-internal-key'] as string | undefined;
  if (internalKey) {
    if (INTERNAL_API_KEY && internalKey === INTERNAL_API_KEY) {
      req.user = { githubUsername: '__internal-service__' };
      next();
      return;
    }
    res.status(401).json({ error: 'Invalid internal service key' });
    return;
  }

  // ── Standard JWT path ──
  const authHeader = req.headers.authorization;
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    res.status(401).json({ error: 'Missing or invalid Authorization header' });
    return;
  }

  const token = authHeader.slice(7); // Remove 'Bearer '

  try {
    const payload = jwt.verify(token, JWT_SECRET, {
      algorithms: [JWT_ALGORITHM],
    }) as { sub?: string; exp?: number };

    if (!payload.sub) {
      res.status(401).json({ error: 'Invalid token: missing subject' });
      return;
    }

    req.user = { githubUsername: payload.sub };
    next();
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Token verification failed';
    res.status(401).json({ error: `Authentication failed: ${message}` });
  }
};
