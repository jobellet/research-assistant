import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a careful research assistant. Answer the user's question using ONLY the context papers "
    "(their titles and abstracts). Give a balanced answer: report the findings that support and those that "
    "contradict or qualify an answer, and the main limitations the papers state. If the papers do not answer "
    "the question, say so plainly. Cite every claim inline as [1], [2] matching the paper numbers. "
    "Write 2-4 short paragraphs; do not invent results, numbers or references."
)


def build_prompt(query: str, context_papers: List[Dict[str, Any]]) -> str:
    context = "\n\n".join(
        f"[{i + 1}] Title: {p.get('title', 'Unknown')}\nAuthors: {p.get('authors', 'Unknown')}"
        f"\nYear: {p.get('year', '')}\nAbstract: {p.get('summary', '')}"
        for i, p in enumerate(context_papers)
    )
    return f"Context papers:\n{context}\n\nQuestion: {query}"


def generate_rag_response(query: str, context_papers: List[Dict[str, Any]], model: str = "phi3"):
    """Stream an answer grounded in the given papers.

    Uses the configured AI provider (API key, see ai_module) when there is one,
    otherwise the optional LLM worker (cluster or local, library/.llm_worker_url).
    """
    from ai_module import provider

    prompt = build_prompt(query, context_papers)
    if provider.is_enabled():
        try:
            yield from provider.stream(prompt, system=SYSTEM_PROMPT)
        except provider.AIError as e:
            yield f"[{e}]"
        return

    url_file = Path("library/.llm_worker_url")
    if not url_file.exists():
        yield ("No AI provider is configured. Add an API key in Settings → AI provider "
               "(OpenAI, Gemini, Claude, Mistral, Groq, OpenRouter or a local Ollama server).")
        return
    import requests
    try:
        worker_url = url_file.read_text().strip()
        response = requests.post(f"{worker_url}/generate", json={"prompt": SYSTEM_PROMPT + "\n\n" + prompt},
                                 stream=True, timeout=120)
        for chunk in response.iter_content(chunk_size=1024):
            if chunk:
                yield chunk.decode("utf-8")
    except Exception as e:
        logger.error(f"Chat generation error: {e}")
        yield f"\n\n[Error communicating with LLM worker: {e}]"
