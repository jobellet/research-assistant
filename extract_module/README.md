# Phase 2: Content Extraction Module

This module is responsible for extracting metadata from scientific PDFs stored in the `library/` directory. It uses `PyMuPDF` for text extraction and a local LLM via `Ollama` for structured metadata generation.

## Prerequisites

1.  **Python Dependencies**:
    - `PyMuPDF` (`fitz`)
    - `ollama`
    Ensure these are installed in your environment (e.g., `pip install PyMuPDF ollama`).

2.  **Ollama (Local Desktop)**:
    - Install Ollama from [ollama.com](https://ollama.com).
    - Ensure the Ollama server is running (usually on `http://localhost:11434`).
    - Pull the `phi3` model:
      ```bash
      ollama pull phi3
      ```

3.  **Cluster Environment (SLURM/Docker)**:
    - If running on a cluster (detected via the `USER` env variable or the `/gpfs01` path), the module will automatically bypass Ollama.
    - It uses `srun` to offload extraction to a GPU node running a `cuda-conda` Docker container.
    - The module executes `run_llm_gpu.py`, which natively loads a small `transformers` model (`deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B`) to extract metadata efficiently.

## Module Structure

- `extractor.py`: The main script that scans the `library/` and coordinates the extraction.
- `pdf_utils.py`: Contains logic for extracting text from the first few pages of a PDF.
- `llm_utils.py`: Handles communication with Ollama and parses JSON metadata.

## Usage

Run the extractor from the root of the project:

```bash
python extract_module/extractor.py --library library --model phi3
```

### Arguments

- `--library`: Path to the library directory (default: `library`).
- `--model`: Ollama model to use (default: `phi3`).
- `--overwrite`: If set, existing `metadata.json` files will be re-generated.

## Output

For each PDF in `library/<hash>/`, the module generates a `metadata.json` file with the following structure:

```json
{
    "title": "...",
    "authors": ["Author 1", "Author 2"],
    "keywords": ["Keyword 1", "Keyword 2"],
    "summary": "..."
}
```
