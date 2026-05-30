import os
import sys

# Add the 'src/' directory to Python's import path
sys.path.insert(0, os.path.abspath("./src"))

try:
    from services.retrieval import get_manual_context
    from core.database import col_knowledge
    
    # 1. Check if the database has manual chunks
    doc_count = col_knowledge.count_documents({})
    print(f"[•] Database contains {doc_count} total manual chunks.")
    
    if doc_count == 0:
        print("[!] Cannot test retrieval: Database collection is empty.")
        sys.exit(0)
        
    # 2. Define a test query
    test_query = "What causes the engine coolant to overheat?"
    print(f"\n[•] Running Test Query: '{test_query}'")
    
    # 3. Retrieve context (temporarily bypassing the 0.55 threshold so we can see all raw scores)
    from core.models import embed_model
    vector = embed_model.encode(test_query).tolist()
    
    results = list(col_knowledge.aggregate([
        {"$vectorSearch": {
            "index": "vector_index",
            "path": "embedding",
            "queryVector": vector,
            "numCandidates": 50,
            "limit": 5
        }},
        {"$project": {
            "_id": 0,
            "source": 1,
            "text": 1,
            "score": {"$meta": "vectorSearchScore"}
        }}
    ]))
    
    print("\n[✓] Raw Vector Search Results (Top 5 Matches):")
    print("-" * 65)
    for i, doc in enumerate(results):
        text_snippet = doc.get("text", "").replace("\n", " ")[:80] + "..."
        print(f"Match {i+1}: Score = {doc.get('score', 0):.4f} | Source: {doc.get('source')} | Text: {text_snippet}")
    print("-" * 65)
    
except Exception as e:
    print(f"[!] Test Failed: {e}")
