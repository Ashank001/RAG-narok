import { Queue } from 'bullmq';

const redisHost = process.env.REDIS_HOST || '127.0.0.1';
const redisPort = parseInt(process.env.REDIS_PORT || '6379', 10);

export const ingestionQueue = new Queue('ingestion-queue', {
  connection: {
    host: redisHost,
    port: redisPort,
  },
});

console.log(`BullMQ initialized queue "ingestion-queue" on Redis at ${redisHost}:${redisPort}`);
