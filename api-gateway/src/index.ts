import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import { connectDB } from './config/db';
import ingestRouter from './routes/ingest';
// Start the BullMQ worker that bridges the queue to the FastAPI Celery task
import './workers/ingestionWorker';


// Load environment variables first so CORS_ORIGINS is available
dotenv.config();

const app = express();
const PORT = process.env.PORT || 3000;

// ---------------------------------------------------------
// CORS — origins read from CORS_ORIGINS env var
// Format: comma-separated list, e.g. "http://localhost:3000,https://app.example.com"
// Falls back to localhost:3000 for local development.
// ---------------------------------------------------------
const allowedOrigins = (process.env.CORS_ORIGINS ?? 'http://localhost:3000')
  .split(',')
  .map((o) => o.trim())
  .filter(Boolean);

app.use(
  cors({
    origin: allowedOrigins,
    credentials: true,
  })
);

// Middleware for parsing JSON payloads
app.use(express.json());

// Routes
app.use('/api', ingestRouter);

// Health check endpoint
app.get('/health', (req, res) => {
  res.status(200).json({ status: 'OK', service: 'API Gateway' });
});

// Initialize database connection and start Express server
const startServer = async () => {
  try {
    // Connect to MongoDB using the connection utility
    await connectDB();

    // Start listening on port
    app.listen(PORT, () => {
      console.log(`API Gateway server running on port ${PORT}`);
    });
  } catch (error) {
    console.error('Failed to start API Gateway server:', error);
    process.exit(1);
  }
};

startServer();
