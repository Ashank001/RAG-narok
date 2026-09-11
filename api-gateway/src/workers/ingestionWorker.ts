import { Worker, Job } from 'bullmq';
import https from 'https';
import http from 'http';
import dotenv from 'dotenv';
import { Session } from '../models/Session';

dotenv.config();

const ragEngineUrl = process.env.RAG_ENGINE_URL || 'http://localhost:8000';
const internalApiKey = process.env.INTERNAL_API_KEY || '';

// ── Startup diagnostics ─────────────────────────────────────────────
// Log a clear warning if RAG_ENGINE_URL looks like it will fail in production
if (!process.env.RAG_ENGINE_URL) {
  console.warn(
    '[BullMQ Worker] ⚠️  RAG_ENGINE_URL is NOT set — falling back to http://localhost:8000. ' +
    'This will fail in containerised deployments (Render, Railway, etc.)!',
  );
} else {
  console.log(`[BullMQ Worker] RAG_ENGINE_URL = ${ragEngineUrl}`);
}

if (!internalApiKey) {
  console.warn(
    '[BullMQ Worker] ⚠️  INTERNAL_API_KEY is NOT set — FastAPI will reject forwarded requests.',
  );
}

// Parse REDIS_URL for Upstash TLS support
function getRedisConnection() {
  const redisUrl = process.env.REDIS_URL;

  if (redisUrl) {
    const url = new URL(redisUrl);
    const tls = url.protocol === 'rediss:';
    return {
      host: url.hostname,
      port: parseInt(url.port || '6379', 10),
      password: url.password || undefined,
      username: url.username || undefined,
      tls: tls ? {} : undefined,
    };
  }

  return {
    host: process.env.REDIS_HOST || '127.0.0.1',
    port: parseInt(process.env.REDIS_PORT || '6379', 10),
  };
}

const connection = getRedisConnection();

interface IngestJobData {
  sessionId: string;
  repositoryUrl: string;
}

function postJson(url: string, body: object, headers: Record<string, string>): Promise<{ statusCode: number; data: string }> {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify(body);
    const parsed = new URL(url);
    const options = {
      hostname: parsed.hostname,
      port: parsed.port || (parsed.protocol === 'https:' ? 443 : 80),
      path: parsed.pathname + parsed.search,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(payload),
        ...headers,
      },
      // 60-second timeout for cold-start scenarios on Render free tier
      timeout: 60_000,
    };

    const lib = parsed.protocol === 'https:' ? https : http;
    const req = lib.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => (data += chunk));
      res.on('end', () => {
        resolve({ statusCode: res.statusCode ?? 0, data });
      });
    });

    req.on('timeout', () => {
      req.destroy();
      reject(new Error(`Request to ${url} timed out after 60s (RAG API may be cold-starting)`));
    });

    req.on('error', (err) => {
      reject(new Error(`Request to ${url} failed: ${err.message}`));
    });

    req.write(payload);
    req.end();
  });
}

/**
 * Posts to the RAG API with retry logic for transient failures.
 * Render free tier returns 429 during cold-starts; the RAG API may
 * return 5xx if it's still initialising heavy ML models.
 */
async function postJsonWithRetry(
  url: string,
  body: object,
  headers: Record<string, string>,
  maxRetries = 5,
): Promise<string> {
  let lastError: Error | null = null;
  let delay = 10_000; // Start with 10s — gives Render time to cold-start

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      const { statusCode, data } = await postJson(url, body, headers);

      if (statusCode >= 200 && statusCode < 300) {
        return data; // Success
      }

      // Retryable: 429 (rate limit / cold-start) or 5xx (server error)
      if (statusCode === 429 || statusCode >= 500) {
        lastError = new Error(`FastAPI responded with ${statusCode}: ${data}`);
        if (attempt < maxRetries) {
          console.warn(
            `[BullMQ Worker] Attempt ${attempt}/${maxRetries} got ${statusCode} — retrying in ${delay / 1000}s...`,
          );
          await new Promise((r) => setTimeout(r, delay));
          delay = Math.min(delay * 2, 120_000); // Exponential backoff, cap at 2min
          continue;
        }
      }

      // Non-retryable 4xx error (401, 403, etc.)
      throw new Error(`FastAPI responded with ${statusCode}: ${data}`);
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err));

      // Network errors (ECONNREFUSED, timeout) are retryable
      if (attempt < maxRetries && !lastError.message.includes('FastAPI responded with 4')) {
        console.warn(
          `[BullMQ Worker] Attempt ${attempt}/${maxRetries} failed: ${lastError.message} — retrying in ${delay / 1000}s...`,
        );
        await new Promise((r) => setTimeout(r, delay));
        delay = Math.min(delay * 2, 120_000);
        continue;
      }

      throw lastError;
    }
  }

  throw lastError ?? new Error('postJsonWithRetry exhausted all retries');
}

const ingestionWorker = new Worker<IngestJobData>(
  'ingestion-queue',
  async (job: Job<IngestJobData>) => {
    const { sessionId, repositoryUrl } = job.data;

    console.log(
      `[BullMQ Worker] Processing job ${job.id} — session: ${sessionId}, repo: ${repositoryUrl}`,
    );
    console.log(
      `[BullMQ Worker] Forwarding to: ${ragEngineUrl}/api/ingest`,
    );

    // ── Immediately update session to "processing" ──────────────
    // This ensures the frontend sees progress even before the Celery
    // task starts. Previously, the session stayed "queued" until the
    // Celery worker called update_session_status(), which could take
    // minutes (or never happen if this forward call fails).
    try {
      await Session.updateOne(
        { sessionId },
        { $set: { status: 'processing' } },
      );
      console.log(`[BullMQ Worker] Updated session ${sessionId} status to "processing".`);
    } catch (dbErr) {
      console.error(`[BullMQ Worker] Failed to update session ${sessionId} to processing:`, dbErr);
      // Non-fatal — continue with the forward attempt
    }

    const endpoint = `${ragEngineUrl}/api/ingest`;

    await postJsonWithRetry(
      endpoint,
      { sessionId, repositoryUrl },
      { 'X-Internal-Key': internalApiKey },
    );

    console.log(`[BullMQ Worker] Forwarded job ${job.id} to FastAPI. Celery task dispatched.`);
  },
  {
    connection,
    concurrency: 1,
  },
);

ingestionWorker.on('completed', (job) => {
  console.log(`[BullMQ Worker] Job ${job.id} completed successfully.`);
});

ingestionWorker.on('failed', async (job, err) => {
  console.error(`[BullMQ Worker] Job ${job?.id} failed: ${err.message}`);
  if (job?.data?.sessionId) {
    try {
      await Session.updateOne(
        { sessionId: job.data.sessionId },
        { $set: { status: 'failed', errorLog: err.message } }
      );
      console.log(`[BullMQ Worker] Updated session ${job.data.sessionId} to failed.`);
    } catch (dbErr) {
      console.error(`[BullMQ Worker] Failed to update session ${job.data.sessionId} status in DB:`, dbErr);
    }
  }
});

ingestionWorker.on('error', (err) => {
  console.error('[BullMQ Worker] Worker error (likely Redis connection issue):', err.message);
});

ingestionWorker.on('stalled', (jobId) => {
  console.warn(`[BullMQ Worker] Job ${jobId} has stalled — may indicate worker crash or Redis timeout.`);
});

console.log(
  `[BullMQ Worker] Listening on "ingestion-queue" — Redis ${connection.host}:${connection.port} → FastAPI ${ragEngineUrl}`,
);

export { ingestionWorker };