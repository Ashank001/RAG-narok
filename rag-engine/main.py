import uvicorn
from fastapi import FastAPI

app = FastAPI(
    title="RAG Engine",
    description="Asynchronous RAG worker API & Health monitor for Engineering Intelligence Hub",
    version="1.0.0"
)

@app.get("/health")
def health():
    return {
        "status": "OK",
        "service": "RAG Engine API"
    }

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
