import json
import logging

STATE_FILE = "stock_state.json"

def clean_state():
    try:
        with open(STATE_FILE, 'r') as f:
            data = json.load(f)
        
        new_data = {}
        for k, v in data.items():
            clean_k = str(k).strip()
            new_data[clean_k] = v
            
        with open(STATE_FILE, 'w') as f:
            json.dump(new_data, f, indent=4)
        
        print(f"Cleaned {len(data)} entries -> {len(new_data)} unique entries.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    clean_state()
