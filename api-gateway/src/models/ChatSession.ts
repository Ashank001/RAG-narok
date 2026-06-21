import { Schema, model, Document } from 'mongoose';

export interface IChatSession extends Document {
  sessionId: string;
  repoUrl: string;
  status: 'pending' | 'processing' | 'completed';
  createdAt: Date;
}

const ChatSessionSchema = new Schema<IChatSession>({
  sessionId: {
    type: String,
    required: true,
    unique: true,
    index: true,
  },
  repoUrl: {
    type: String,
    required: true,
  },
  status: {
    type: String,
    enum: ['pending', 'processing', 'completed'],
    default: 'pending',
    required: true,
  },
  createdAt: {
    type: Date,
    default: Date.now,
    required: true,
  },
});

export const ChatSession = model<IChatSession>('ChatSession', ChatSessionSchema);
