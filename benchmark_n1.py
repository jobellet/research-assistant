import time
import shutil
import tempfile
import sys
import logging
import os
from pathlib import Path

# Mock torch properly
from unittest import mock
import numpy as np

mock_torch = mock.MagicMock()
mock_torch.nn.functional.normalize.return_value.tolist.return_value = [[0.1]*256]
sys.modules["torch"] = mock_torch
sys.modules["torch.nn"] = mock_torch.nn
sys.modules["torch.nn.functional"] = mock_torch.nn.functional

mock_st = mock.MagicMock()
mock_st.encode.return_value = [[0.1]*256]
sys.modules["sentence_transformers"] = mock.MagicMock(SentenceTransformer=mock.MagicMock(return_value=mock_st))

from db_module.db_manager import DBManager
from processor_module.processor import ManuscriptProcessor

logging.basicConfig(level=logging.ERROR)

def setup_benchmark():
    tmp_library = Path("tmp_bench_library")
    if tmp_library.exists():
        shutil.rmtree(tmp_library)
    tmp_library.mkdir()

    tmp_inbox = Path("tmp_bench_inbox")
    if tmp_inbox.exists():
        shutil.rmtree(tmp_inbox)
    tmp_inbox.mkdir()

    num_docs = 1000
    for i in range(num_docs):
        doc_dir = tmp_library / f"hash_{i}"
        doc_dir.mkdir()
        with open(doc_dir / "metadata.json", "w") as f:
            f.write('{"title": "Test Paper", "pdf_filename": "paper.pdf"}')

    db = DBManager()

    # Pre-populate DB with some docs
    ids = [f"hash_{i}" for i in range(num_docs)]
    metadatas = [{"title": "Test Paper", "pdf_filename": "paper.pdf"} for _ in range(num_docs)]
    documents = ["test document"] * num_docs

    # We batch insert
    # To fix the mocked embedding problem we can provide mock embeddings
    embeddings = [[0.1] * 256 for _ in range(num_docs)]
    db.collection.add(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embeddings
    )

    return tmp_library, tmp_inbox, db

def run_benchmark():
    tmp_library, tmp_inbox, db = setup_benchmark()

    processor = ManuscriptProcessor(library_dir=str(tmp_library), inbox_dir=str(tmp_inbox))
    processor.db_manager = db

    start_time = time.time()
    processor._handle_indexing()
    end_time = time.time()

    duration = end_time - start_time
    print(f"Benchmark _handle_indexing took {duration:.4f} seconds.")

    shutil.rmtree(tmp_library)
    shutil.rmtree(tmp_inbox)
    return duration

if __name__ == "__main__":
    run_benchmark()
