import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

def generate_rag_response(query: str, context_papers: List[Dict[str, Any]], model: str = "phi3"):
    import os
    from pathlib import Path
    import requests
    import json
    
    url_file = Path("library/.llm_worker_url")
    use_worker = url_file.exists()
    
    context_str = "\n\n".join([
        f"[{i+1}] Title: {p.get('title', 'Unknown')}\nAuthors: {p.get('authors', 'Unknown')}\nSummary: {p.get('summary', '')}" 
        for i, p in enumerate(context_papers)
    ])
    
    prompt = f"""You are a helpful AI research assistant. Answer the user's question based ONLY on the provided Context Papers.
If the context doesn't contain the answer, explicitly state that. Do not use outside knowledge.
Use inline citations like [1], [2] when referencing the papers to back up your claims.

Context Papers:
{context_str}

User Question: {query}
"""

    try:
        if use_worker:
            worker_url = url_file.read_text().strip()
            
            response = requests.post(
                f"{worker_url}/generate",
                json={"prompt": prompt},
                stream=True
            )
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    yield chunk.decode('utf-8')
        else:
            yield "The AI Chat server is currently offline. Please click 'Activate AI Chat' in the UI to start the local Gemma 4 worker."

    except Exception as e:
        logger.error(f"Chat generation error: {e}")
        yield f"\n\n[Error communicating with LLM worker: {str(e)}]"
