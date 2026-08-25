import os
import sys
import logging
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import uvicorn
import google.generativeai as genai
from pathlib import Path

# --- Simple .env loader ---
def load_env():
    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.strip() and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip().strip('"').strip("'")

load_env()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Configure Gemini
api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if not api_key:
    logger.error("Gemini API key not found in environment or .env file.")
else:
    genai.configure(api_key=api_key)
    logger.info("Gemini API configured successfully.")
    try:
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        logger.info(f"Available models: {models}")
    except Exception as e:
        logger.error(f"Failed to list models: {e}")

# Lightest model: gemini-flash-lite-latest
MODEL_NAME = "models/gemini-flash-lite-latest"
logger.info(f"Using Gemini model: {MODEL_NAME}")

@app.post("/generate")
async def generate(request: Request):
    if not api_key:
        return StreamingResponse(iter(["Error: GEMINI_API_KEY not configured on worker."]), media_type="text/plain")
        
    data = await request.json()
    prompt = data.get("prompt", "")
    
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        # Use streaming generation
        response = model.generate_content(prompt, stream=True)
        
        async def generator():
            for chunk in response:
                if chunk.text:
                    yield chunk.text
                    
        return StreamingResponse(generator(), media_type="text/plain")
    except Exception as e:
        logger.error(f"Gemini generation error: {e}")
        return StreamingResponse(iter([f"Error: {str(e)}"]), media_type="text/plain")

@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_NAME}

if __name__ == "__main__":
    port = 8080
    host = "127.0.0.1"
    url_file = os.path.join(os.getcwd(), "library", ".llm_worker_url")
    
    # Ensure library directory exists
    os.makedirs(os.path.dirname(url_file), exist_ok=True)
    
    with open(url_file, "w") as f:
        f.write(f"http://{host}:{port}")
    
    logger.info(f"Gemini LLM Worker running at http://{host}:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
