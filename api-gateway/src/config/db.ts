import mongoose from 'mongoose';

export const connectDB = async (): Promise<void> => {
  const mongoUri = process.env.MONGO_URI;
  if (!mongoUri) {
    console.error('MONGO_URI is not defined in the environment variables');
    process.exit(1);
  }

  try {
    const conn = await mongoose.connect(mongoUri, { dbName: 'api-gateway' });
    console.log(`Successfully connected to MongoDB cluster [Host: ${conn.connection.host}, Database: ${conn.connection.name}]`);
  } catch (error) {
    console.error('Failed to connect to MongoDB cluster:', error);
    process.exit(1);
    
  }
};
