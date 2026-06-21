import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import { connectDB } from './config/db';
import ingestRouter from './routes/ingest';

// Load environment variables
dotenv.config();

const app = express();
const PORT = process.env.PORT || 3000;

// Enable Cross-Origin Resource Sharing (CORS)
app.use(cors());

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
