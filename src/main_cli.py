from services.llm_agent import generate_diagnostic

if __name__ == "__main__":
    test_vin = "VIN_12345_TEST"
    print(f"--- CONNECTED TO CAR: {test_vin} ---")
    print("Type 'exit' to stop.\n")
    
    chat_history = []
    
    while True:
        q = input("You: ").strip()
        if q.lower() in ["exit", "quit", "bye", "stop"]:
            print("🔌 Disconnecting...")
            break
            
        if q:
            print("Thinking...", end="\r")
            try:
                response = generate_diagnostic(q, chat_history, test_vin)
                
                chat_history.append(f"User: {q}")
                chat_history.append(f"AI: {response}")
                
                # Keep chat history size bounded to avoid memory creep
                chat_history = chat_history[-10:]
                
                print(" " * 20, end="\r") 
                print(f"AI: {response}\n")
            except Exception as e:
                print(" " * 20, end="\r")
                print(f"[!] Error: {e}\n")