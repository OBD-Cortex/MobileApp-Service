from services.llm_agent import generate_diagnostic
from core.config import TARGET_VIN

if __name__ == "__main__":
    print(f"--- CONNECTED TO CAR: {TARGET_VIN} ---")
    print("Type 'exit' to stop.\n")
    
    chat_history = []
    
    while True:
        q = input("You: ").strip()
        if q.lower() in ["exit", "quit", "bye", "stop"]:
            print("🔌 Disconnecting...")
            break
            
        if q:
            print("Thinking...", end="\r")
            response = generate_diagnostic(q, chat_history)
            
            chat_history.append(f"User: {q}")
            chat_history.append(f"AI: {response}")
            
            print(" " * 20, end="\r") 
            print(f"AI: {response}\n")