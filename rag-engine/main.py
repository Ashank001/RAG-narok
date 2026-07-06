import os
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

# Celery task import
from worker import process_repository

# LangChain & AI Imports
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_mongodb import MongoDBAtlasVectorSearch
from langchain_core.prompts import ChatPromptTemplate
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

class IngestRequest(BaseModel):
    sessionId: str
    repositoryUrl: str

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
# 4. LangChain Prompt & Chain (built dynamically per-request in /chat)
# ---------------------------------------------------------
# The chat endpoint constructs the prompt at request time based on
# whether vector context was retrieved. This avoids crashes when the
# collection is empty (no repos ingested yet).


# ---------------------------------------------------------
# 5. API Endpoints
# ---------------------------------------------------------
@app.post("/api/ingest", status_code=202)
async def ingest(request: IngestRequest):
    """
    Accepts a sessionId and repositoryUrl, dispatches the ingestion
    task to the Celery worker via Redis, and returns immediately.
    """
    process_repository.delay(
        payload={"sessionId": request.sessionId, "repositoryUrl": request.repositoryUrl}
    )
    return JSONResponse(
        status_code=202,
        content={
            "message": "Ingestion started in the background.",
            "sessionId": request.sessionId,
        },
    )

@app.get("/health")
def health():
    return {"status": "ok", "service": "rag-engine-active"}

@app.post("/chat/{session_id}")
async def chat(session_id: str, request: ChatRequest):
    """
    RAG-powered chat endpoint:
    1. Converts the user's query into a vector via GoogleGenerativeAIEmbeddings.
    2. Performs similarity search on rag_db.code_vectors via MongoDBAtlasVectorSearch.
    3. If context is found, injects it into a system prompt alongside the user's question.
    4. If the collection is empty (no repos ingested), falls back to a direct LLM call.
    5. Streams Gemini's response back to the frontend as SSE chunks.
    """
    if not request.query or not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    user_query = request.query.strip()

    async def generate_stream():
        try:
            # -------------------------------------------------
            # Step 1: Retrieve relevant code chunks from Atlas
            # -------------------------------------------------
            context_text = ""
            try:
                retrieved_docs = vector_store.similarity_search(user_query, k=4)
                if retrieved_docs:
                    context_text = "\n\n---\n\n".join(
                        doc.page_content for doc in retrieved_docs
                    )
                    print(f"[Chat | {session_id}] Retrieved {len(retrieved_docs)} chunks for query.")
                else:
                    print(f"[Chat | {session_id}] No matching documents found in vector store.")
            except Exception as retrieval_err:
                # Gracefully handle empty collection / missing index
                print(f"[Chat | {session_id}] Retrieval skipped (empty DB or index not ready): {retrieval_err}")

            # -------------------------------------------------
            # Step 2: Build prompt based on whether context exists
            # -------------------------------------------------
            if context_text:
                # RAG mode: inject retrieved codebase context
                chat_prompt = ChatPromptTemplate.from_messages([
                    ("system",
                     "You are an elite software architecture assistant named RAGnarok. "
                     "Use the following retrieved codebase snippets to answer the user's question accurately. "
                     "Reference specific file names, functions, or patterns from the context when relevant. "
                     "If the answer is not contained within the provided context, state that clearly. "
                     "Do not hallucinate code that isn't there.\n\n"
                     "Codebase Context:\n{context}"),
                    ("human", "{question}")
                ])
                chain = chat_prompt | llm | StrOutputParser()
                stream_input = {"context": context_text, "question": user_query}
            else:
                # Fallback mode: no context available, answer directly
                chat_prompt = ChatPromptTemplate.from_messages([
                    ("system",
                     "You are an elite software architecture assistant named RAGnarok. "
                     "No codebase has been ingested yet, so you have no repository context. "
                     "Answer the user's question using your general knowledge. "
                     "If the question seems to be about a specific codebase, suggest they ingest "
                     "a repository first using the Ingest Repository panel."),
                    ("human", "{question}")
                ])
                chain = chat_prompt | llm | StrOutputParser()
                stream_input = {"question": user_query}

            # -------------------------------------------------
            # Step 3: Stream the LLM response as SSE
            # -------------------------------------------------
            async for chunk in chain.astream(stream_input):
                yield f"data: {json.dumps({'text': chunk})}\n\n"

            # Send completion signal
            yield f"data: {json.dumps({'done': True})}\n\n"

        except Exception as e:
            print(f"[Chat | {session_id}] Streaming Error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate_stream(), media_type="text/event-stream")