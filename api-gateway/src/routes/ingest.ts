import { Router, Request, Response, RequestHandler } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { Session } from '../models/Session';
import { ingestionQueue } from '../config/queue';
import { validateGithubUrl } from '../middleware/validateGithubUrl';

const router = Router();

interface IngestRequestBody {
  repository_url?: string;
}

const ingestHandler: RequestHandler = async (req: Request, res: Response): Promise<void> => {
  try {
    const { repository_url } = req.body as IngestRequestBody;

    if (!repository_url) {
      res.status(400).json({ error: 'repository_url is required' });
      return;
    }

    // Generate unique session ID
    const sessionId = uuidv4();

    // Create session in MongoDB with a 'queued' status
    const session = new Session({
      sessionId,
      repositoryUrl: repository_url,
      status: 'queued',
    });
    await session.save();

    // Push job to BullMQ queue 'ingestion-queue'
    await ingestionQueue.add('ingest-job', {
      sessionId,
      repositoryUrl: repository_url,
    });

    console.log(`Ingest job added for session ${sessionId} and repository ${repository_url}`);

    // Return 202 Accepted with the sessionId
    res.status(202).json({
      sessionId,
      status: 'queued',
    });
  } catch (error) {
    console.error('Error handling ingestion request:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
};

const statusHandler: RequestHandler = async (req: Request, res: Response): Promise<void> => {
  try {
    const { sessionId } = req.params;

    if (!sessionId) {
      res.status(400).json({ error: 'sessionId parameter is required' });
      return;
    }

    // Query MongoDB for the session
    const session = await Session.findOne({ sessionId });

    if (!session) {
      res.status(404).json({ error: `Session with ID ${sessionId} not found` });
      return;
    }

    // Return 200 with current status and errorLog
    res.status(200).json({
      status: session.status,
      errorLog: session.errorLog || null,
    });
  } catch (error) {
    console.error('Error fetching session status:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
};

router.post('/ingest', validateGithubUrl, ingestHandler);
router.get('/status/:sessionId', statusHandler);

export default router;
