import os
import sys

# Add the 'src/' directory to Python's import path
sys.path.insert(0, os.path.abspath("./src"))

try:
    from core.models import embed_model
    
    test_phrase = "Engine diagnostic troubleshooting"
    print(f"[•] Input text: '{test_phrase}'")
    
    # Run the embedding wrapper
    vector = embed_model.encode(test_phrase)
    
    print("[✓] API Connection Successful!")
    print(f"[•] Vector Dimension Count: {len(vector)}")
    print(f"[•] First 5 vector coordinates: {vector[:5]}")
    
except Exception as e:
    print(f"[!] Test Failed: {e}")
