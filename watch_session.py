import os, certifi, time
from dotenv import load_dotenv
load_dotenv('rag-engine/.env')
from pymongo import MongoClient
client = MongoClient(os.getenv('MONGO_URI'), tlsCAFile=certifi.where(), tlsAllowInvalidCertificates=True)
db = client['api-gateway']
sid = '56a36379-75fd-4b5b-8167-7513c9a0219d'
for i in range(25):
    s = db.sessions.find_one({'sessionId': sid}, {'status':1,'errorLog':1,'repositoryUrl':1,'_id':0})
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {s}")
    if s and s.get('status') in ('completed', 'failed'):
        break
    time.sleep(10)
