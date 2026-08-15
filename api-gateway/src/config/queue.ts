import { Queue } from 'bullmq';

// Parse REDIS_URL if provided (Upstash uses rediss:// with TLS)
// Falls back to REDIS_HOST/PORT for local development
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

  // Local fallback
  return {
    host: process.env.REDIS_HOST || '127.0.0.1',
    port: parseInt(process.env.REDIS_PORT || '6379', 10),
  };
}

const connection = getRedisConnection();

export const ingestionQueue = new Queue('ingestion-queue', { connection });

console.log(`BullMQ initialized queue "ingestion-queue" on Redis at ${connection.host}:${connection.port}`);