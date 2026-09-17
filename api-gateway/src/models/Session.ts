import mongoose, { Schema, Document } from 'mongoose';

export interface ISession extends Document {
  sessionId: string;
  githubUsername?: string;
  repositoryUrl: string;
  status: 'queued' | 'processing' | 'completed' | 'failed';
  errorLog?: string;
  statusMessage?: string;
  createdAt: Date;
}

const SessionSchema: Schema = new Schema<ISession>({
  sessionId: { 
    type: String, 
    required: true, 
    unique: true, 
    index: true 
  },
  githubUsername: {
    type: String,
    index: true,
    // Not `required` at the Mongoose level so legacy sessions without
    // this field remain valid. New sessions always set it.
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
  statusMessage: { 
    type: String 
  },
  createdAt: { 
    type: Date, 
    default: Date.now, 
    required: true 
  }
});

export const Session = mongoose.model<ISession>('Session', SessionSchema);
