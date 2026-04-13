import asyncio
from unittest.mock import MagicMock
from rag.vector_store import search

async def verify_vector_threshold():
    print("--- Testing Vector Similarity Threshold ---")
    
    mock_index = MagicMock()
    # Mock return value for query
    mock_index.query.return_value = {
        "matches": [
            {"id": "doc1", "score": 0.85, "metadata": {"text": "high score"}},
            {"id": "doc2", "score": 0.70, "metadata": {"text": "boundary score"}},
            {"id": "doc3", "score": 0.69, "metadata": {"text": "low score"}}
        ]
    }
    
    query_vector = [0.1, 0.2]  # Just use a list
    # Need to mock the list's tolist() method if the real function calls it
    # But wait, vector_store.py calls query_vector.tolist()
    
    class MockVector:
        def tolist(self): return [0.1, 0.2]
    
    results = await search(mock_index, MockVector(), role="user", top_k=5)
    
    # Assertions
    assert len(results) == 2
    assert results[0]["id"] == "doc1"
    assert results[1]["id"] == "doc2"
    
    # Test empty results case
    mock_index.query.return_value = {
        "matches": [
            {"id": "doc4", "score": 0.50, "metadata": {"text": "very low score"}}
        ]
    }
    results_empty = await search(mock_index, query_vector, role="user", top_k=5)
    assert len(results_empty) == 0
    
    print("\n--- Vector Threshold Verification PASSED ---")

if __name__ == "__main__":
    asyncio.run(verify_vector_threshold())
