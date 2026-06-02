import httpx
import requests
import json

ROUTER_URL = "http://localhost:8000/execute"
OLLAMA_URL = "http://host.docker.internal:11434/api/chat"

# 1. Hermes'in kullanabileceği Sandbox Yürütme Aracı (Tool Function)
async def run_in_sandbox(command: str) -> str:
    """
    Güvenli Docker Sandbox konteyneri içinde Linux (Node.js/Bash) komutları çalıştırır.
    """
    try:
     async with httpx.AsyncClient(timeout=90.0) as client:
            http_response = await client.post(ROUTER_URL, json={"command": command}, timeout=65.0)
            http_response.raise_for_status()
            response = http_response.json()
        return json.dumps(response.json(), indent=2)
    except Exception as e:
        return f"Router bağlantı hatası: {str(e)}"

# 2. Ollama'ya bu aracı bir 'Tool' olarak tanıtma tanımı
sandbox_tool_definition = {
    "type": "function",
    "function": {
        "name": "run_in_sandbox",
        "description": "Izole Docker Linux ortamında güvenli komut, script veya test çalıştırmak için bu aracı kullan.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Çalıştırılacak Linux terminal komutu. Örn: 'node -e \"console.log(1+1)\"'"
                }
            },
            "required": ["command"]
        }
    }
}

# 3. Hermes Akıl Yürütme ve Karar Mekanizması
def ask_hermes(user_prompt: str):
    print(f"\n[USER]: {user_prompt}")
    
    payload = {
        "model": "qwen2.5-coder:7b",
        "messages": [
            {"role": "system", "content": "Sen Hermes Agent'ın beynisin. Kod yazma, dosya okuma/yazma veya test çalıştırma isteklerinde 'run_in_sandbox' aracını çağırmalısın. Sadece listedeki güvenli komutları üret."},
            {"role": "user", "content": user_prompt}
        ],
        "tools": [sandbox_tool_definition],
        "stream": False
    }
    
    try:
        res = requests.post(OLLAMA_URL, json=payload).json()
        message = res.get("message", {})
        
        # Model bir araç çağırmak istedi mi?
        if "tool_calls" in message:
            for tool_call in message["tool_calls"]:
                func_name = tool_call["function"]["name"]
                arguments = tool_call["function"]["arguments"]
                
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                
                cmd_to_run = arguments.get("command")
                
                print(f"\n🤖 [HERMES DECISION]: Kod çalıştırmam gerekiyor. '{func_name}' aracını çağırıyorum...")
                print(f"💻 [COMMAND]: {cmd_to_run}")
                
                # Aracı çalıştır ve sonucu al
                sandbox_result = await run_in_sandbox(cmd_to_run)
                print(f"\n📦 [SANDBOX OUTPUT]:\n{sandbox_result}")
        else:
            print(f"\n🤖 [HERMES]: {message.get('content')}")
            
    except Exception as e:
        print(f"Ollama bağlantı hatası: {str(e)}. Ollama'nın arka planda açık olduğundan emin olun.")

if __name__ == "__main__":
    # Test: Ajanın kod yazıp çalıştırma kararı alması
    ask_hermes("Bana 1'den 10'a kadar olan sayıların karelerini ekrana basan bir Node.js kodu yaz ve çalıştır.")
