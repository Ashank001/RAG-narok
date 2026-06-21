import mongoose, { Schema, Document } from 'mongoose';

export interface ISession extends Document {
  sessionId: string;
  repositoryUrl: string;
  status: 'queued' | 'processing' | 'completed' | 'failed';
  errorLog?: string;
  createdAt: Date;
}

const SessionSchema: Schema = new Schema<ISession>({
  sessionId: { 
    type: String, 
    required: true, 
    unique: true, 
    index: true 
  },
  repositoryUrl: { 
    type: String, 
    required: true 
  },
  status: {
    type: String,
    enum: ['queued', 'processing', 'completed', 'failed'],
    default: 'queued',
    required: true
  },
  errorLog: { 
    type: String 
  },
  createdAt: { 
    type: Date, 
    default: Date.now, 
    required: true 
  }
});

export const Session = mongoose.model<ISession>('Session', SessionSchema);
