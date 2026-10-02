import os
from dotenv import load_dotenv
from pymongo import MongoClient
import certifi

load_dotenv()
client = MongoClient(os.getenv('MONGO_URI'), tlsCAFile=certifi.where(), tlsAllowInvalidCertificates=True)
coll = client['rag_db']['code_vectors']

query_vector = [0.1]*3072 # Dummy

def search(filter_doc):
    pipeline = [
        {
            '$vectorSearch': {
                'index': 'vector_index',
                'path': 'embedding',
                'queryVector': query_vector,
                'numCandidates': 50,
                'limit': 5,
                'filter': filter_doc
            }
        }
    ]
    return list(coll.aggregate(pipeline))

sess_id = '05858bdd-d7ea-4349-84de-1c9bfc1f278f'

print('Test C: post filter')
pipeline2 = [
    {
        '$vectorSearch': {
            'index': 'vector_index',
            'path': 'embedding',
            'queryVector': query_vector,
            'numCandidates': 50,
            'limit': 5,
        }
    },
    {
        '$match': { 'session_id': sess_id }
    }
]
try:
    print('post count:', len(list(coll.aggregate(pipeline2))))
except Exception as e:
    print('Error:', e)

print('Test A: session_id = sess_id')
try:
    print('pre count:', len(search({'session_id': sess_id})))
except Exception as e:
    print('Error:', e)

print('Test B: session_id = { $eq: sess_id }')
try:
    print('pre eq count:', len(search({'session_id': {'$eq': sess_id}})))
except Exception as e:
    print('Error:', e)
