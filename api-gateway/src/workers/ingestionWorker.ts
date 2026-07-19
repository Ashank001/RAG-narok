import { Worker, Job } from 'bullmq';
import https from 'https';
import http from 'http';
import dotenv from 'dotenv';

dotenv.config();

const redisHost = process.env.REDIS_HOST || '127.0.0.1';
const redisPort = parseInt(process.env.REDIS_PORT || '6379', 10);
const ragEngineUrl = process.env.RAG_ENGINE_URL || 'http://localhost:8000';
const internalApiKey = process.env.INTERNAL_API_KEY || '';

interface IngestJobData {
  sessionId: string;
  repositoryUrl: string;
}

/**
 * Thin HTTP wrapper — avoids pulling in axios just for one POST.
 * Sends a JSON POST to the given URL and resolves with the response body.
 */
function postJson(url: string, body: object, headers: Record<string, string>): Promise<string> {
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
    };

    const lib = parsed.protocol === 'https:' ? https : http;
    const req = lib.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => (data += chunk));
      res.on('end', () => {
        if (res.statusCode && res.statusCode >= 400) {
          reject(new Error(`FastAPI responded with ${res.statusCode}: ${data}`));
        } else {
          resolve(data);
        }
      });
    });

    req.on('error', reject);
    req.write(payload);
    req.end();
  });
}

/**
 * BullMQ Worker — consumes jobs from "ingestion-queue" and forwards them
 * to the FastAPI rag-engine's /api/ingest endpoint, which in turn dispatches
 * the Celery task.  This bridges the Node (BullMQ) and Python (Celery) worlds.
 */
const ingestionWorker = new Worker<IngestJobData>(
  'ingestion-queue',
  async (job: Job<IngestJobData>) => {
    const { sessionId, repositoryUrl } = job.data;

    console.log(
      `[BullMQ Worker] Processing job ${job.id} — session: ${sessionId}, repo: ${repositoryUrl}`,
    );

    const endpoint = `${ragEngineUrl}/api/ingest`;

    await postJson(
      endpoint,
      { sessionId, repositoryUrl },
      // Use the shared internal key so FastAPI skips JWT validation
      { 'X-Internal-Key': internalApiKey },
    );

    console.log(`[BullMQ Worker] Forwarded job ${job.id} to FastAPI. Celery task dispatched.`);
  },
  {
    connection: {
      host: redisHost,
      port: redisPort,
    },
    // Process one job at a time to avoid hammering the embedding API
    concurrency: 1,
  },
);

ingestionWorker.on('completed', (job) => {
  console.log(`[BullMQ Worker] Job ${job.id} completed successfully.`);
});

ingestionWorker.on('failed', (job, err) => {
  console.error(`[BullMQ Worker] Job ${job?.id} failed: ${err.message}`);
});

console.log(
  `[BullMQ Worker] Listening on "ingestion-queue" — Redis ${redisHost}:${redisPort} → FastAPI ${ragEngineUrl}`,
);

export { ingestionWorker };
