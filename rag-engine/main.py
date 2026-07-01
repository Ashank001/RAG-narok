import os
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# LangChain & AI Imports
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_mongodb import MongoDBAtlasVectorSearch
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables securely from .env
load_dotenv()

app = FastAPI()

# ---------------------------------------------------------
# 1. Setup CORS Middleware for Next.js
# ---------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    query: str

# ---------------------------------------------------------
# 2. Database & Vector Store Configuration
# ---------------------------------------------------------
MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    raise ValueError("CRITICAL: MONGO_URI missing from .env")

# Connect to Atlas using synchronous MongoClient for LangChain
mongo_client = MongoClient(MONGO_URI)

# IMPORTANT: Ensure these match what you set in your ingestion worker!
DB_NAME = "rag_db" 
COLLECTION_NAME = "code_vectors" 
collection = mongo_client[DB_NAME][COLLECTION_NAME]

# Initialize Google's Embedding Model (translates text to vectors)
embeddings = GoogleGenerativeAIEmbeddings(model="gemini-embedding-001")

# Initialize MongoDB Atlas Vector Search integration
vector_store = MongoDBAtlasVectorSearch(
    collection=collection,
    embedding=embeddings,
    index_name="vector_index", # Name of the Atlas Search Index you will create
    text_key="text",
    embedding_key="embedding",
)

# Set up the Retriever to fetch the 4 closest matching code chunks
retriever = vector_store.as_retriever(search_kwargs={"k": 4})

# ---------------------------------------------------------
# 3. LLM Configuration (Google Gemini)
# ---------------------------------------------------------
# Initialize Gemini 1.5 Flash with streaming enabled
# Initialize Gemini with a supported version
# Initialize Gemini with the current 2026 stable version
llm = ChatGoogleGenerativeAI(
    model="gemini-3.5-flash",
    temperature=0.2, 
    streaming=True
)
# ---------------------------------------------------------
# 4. LangChain LCEL Pipeline Setup
# ---------------------------------------------------------
system_prompt = (
    "You are an elite software architecture assistant named RAGnarok. "
    "Use the following retrieved codebase snippets to answer the user's question accurately. "
    "If the answer is not contained within the provided context, state that clearly. "
    "Do not hallucinate code that isn't there.\n\n"
    "Codebase Context:\n{context}"
)

prompt = ChatPromptTemplate.from_messages([
    ("system", system_prompt),
    ("human", "{question}")
])

def format_docs(docs):
    return "\n\n---\n\n".join(doc.page_content for doc in docs)

# The core LCEL Chain: Retrieve -> Format -> Prompt -> LLM -> Parse String
rag_chain = (
    {"context": retriever | format_docs, "question": RunnablePassthrough()}
    | prompt
    | llm
    | StrOutputParser()
)

# ---------------------------------------------------------
# 5. API Endpoints
# ---------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "service": "rag-engine-active"}

@app.post("/chat/{session_id}")
async def chat(session_id: str, request: ChatRequest):
    """
    Retrieves semantic code matches from Atlas and streams Gemini's analysis.
    """
    if not request.query or not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    async def generate_stream():
        try:
            # Asynchronously stream chunks directly from the LCEL chain
            async for chunk in rag_chain.astream(request.query):
                # Format payload as Server-Sent Events (SSE) for frontend ingestion
                yield f"data: {json.dumps({'text': chunk})}\n\n"
            
            # Send completion signal
            yield f"data: {json.dumps({'done': True})}\n\n"
            
        except Exception as e:
            print(f"Streaming Error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate_stream(), media_type="text/event-stream")