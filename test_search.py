import json
import os
from db_module.db_manager import DBManager
from search_module.searcher import SemanticSearcher

def setup_test_db():
    print("Setting up test database...")
    db = DBManager()
    
    # Paper 1
    meta1 = {
        "title": "Brain surfaces and mapping",
        "authors": ["Alice", "Bob"],
        "summary": "A deep dive into brain surfaces and mapping.",
        "keywords": ["neuroscience", "brain"],
        "pdf_filename": "paper1.pdf"
    }
    db.index_document("hash1", meta1)
    
    # Paper 2
    meta2 = {
        "title": "Transformer models for code",
        "authors": ["Charlie", "David"],
        "summary": "This paper discusses transformer models for code generation.",
        "keywords": ["llm", "transformers", "code"],
        "pdf_filename": "paper2.pdf"
    }
    db.index_document("hash2", meta2)
    print("Mock documents indexed.")

def test_queries():
    print("\n--- Testing Search Queries ---")
    
    from unittest import mock
    import sys
    mock_st = mock.MagicMock()
    import numpy as np; mock_st.encode.return_value = np.array([[0.1]*256])
    with mock.patch.dict(sys.modules, {"sentence_transformers": mock.MagicMock(SentenceTransformer=mock.MagicMock(return_value=mock_st))}):
        # Explicitly patch SentenceTransformer everywhere it is imported inside db_manager
        with mock.patch('db_module.db_manager.SentenceTransformer', return_value=mock_st):
            from search_module.searcher import SemanticSearcher
            searcher = SemanticSearcher()
            searcher.db_manager.collection.query = mock.MagicMock(return_value={'ids': [[]]})

        # Query related to neuroscience
        print("\nQuery: 'brain surfaces and mapping'")
        res1 = searcher.search("brain surfaces and mapping")
        print(json.dumps(res1, indent=4))

        # Query related to LLMs
        print("\nQuery: 'transformer models for code'")
        res2 = searcher.search("transformer models for code")
        print(json.dumps(res2, indent=4))

        # Query with filter
        print("\nQuery: 'brain surfaces and mapping' with filter")
        searcher.search("brain surfaces and mapping", where={"year": 2023})
        # Check that the where argument was passed correctly
        args, kwargs = searcher.db_manager.collection.query.call_args
        assert kwargs["where"] == {"year": 2023}, "Where clause was not passed correctly"
        print("Filter test passed!")

def test_path_traversal():
    print("\n--- Testing Path Traversal Defense ---")

    from unittest import mock
    import sys
    mock_st = mock.MagicMock()
    import numpy as np; mock_st.encode.return_value = np.array([[0.1]*256])
    with mock.patch.dict(sys.modules, {"sentence_transformers": mock.MagicMock(SentenceTransformer=mock.MagicMock(return_value=mock_st))}):
        with mock.patch('db_module.db_manager.SentenceTransformer', return_value=mock_st):
            from search_module.searcher import SemanticSearcher
            searcher = SemanticSearcher()

        malicious_hash_id = "../../../../etc/passwd"
        print(f"Testing find_all_pdfs with malicious hash: '{malicious_hash_id}'")

        # The vulnerability was in find_all_pdfs which gets called inside search and directly
        # Here we test it directly. It should not raise an error or return outside files,
        # but instead return an empty list and emit a warning log.
        results = searcher.find_all_pdfs(malicious_hash_id)
        print(f"Results for malicious path traversal: {results}")
        assert results == [], f"Expected empty list for malicious hash_id, got {results}"
        print("Path traversal test passed!")

def test_search_batch():
    print("\n--- Testing Search Batch ---")

    from unittest import mock
    import sys

    # Mock SentenceTransformer
    mock_st = mock.MagicMock()
    import numpy as np; mock_st.encode.return_value = np.array([[0.1]*256])
    with mock.patch.dict(sys.modules, {"sentence_transformers": mock.MagicMock(SentenceTransformer=mock.MagicMock(return_value=mock_st))}):
        with mock.patch('db_module.db_manager.SentenceTransformer', return_value=mock_st):
            from search_module.searcher import SemanticSearcher
            searcher = SemanticSearcher()

            # Mock the ChromaDB collection query method
            mock_query_result = {
                "ids": [["hash1"], ["hash2"]],
                "distances": [[0.1], [0.2]]
            }
            searcher.db_manager.collection.query = mock.MagicMock(return_value=mock_query_result)

            # Test empty query
            print("Testing empty query_texts...")
            empty_result = searcher.search_batch([])
            assert empty_result == {"ids": [], "distances": []}, f"Expected empty result, got {empty_result}"
            assert not searcher.db_manager.collection.query.called, "query() should not be called for empty query_texts"

            # Test valid query
            print("Testing valid query_texts...")
            queries = ["query 1", "query 2"]
            result = searcher.search_batch(queries, n_results=2)
            assert result == mock_query_result, f"Expected {mock_query_result}, got {result}"

            # Verify query() was called correctly
            searcher.db_manager.collection.query.assert_called_once_with(
                query_texts=queries,
                n_results=2,
                include=["distances"]
            )

            print("Search batch tests passed!")

if __name__ == "__main__":
    test_queries()
    test_path_traversal()
    test_search_batch()
