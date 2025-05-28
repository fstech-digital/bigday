import os
import json
import time
from typing import Dict, Any
from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv
from pydantic import RootModel
from openai import OpenAI

load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
INSTRUCTION = os.getenv("INSTRUCTION")

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
app = FastAPI()

class EventMap(RootModel[Dict[str, Dict[str, str]]]):
    pass

class DeepSeekProcessor:
    def __init__(self, instruction: str, client: OpenAI):
        self.instruction = instruction
        self.client = client
        self.brand_lookup = self.carregar_lookup("../brands.json")

    def carregar_lookup(self, caminho: str) -> Dict[str, int]:
        with open(caminho, encoding="utf-8") as f:
            brands = json.load(f)
            return {b["name"]: b["id"] for b in brands}

    def limpar_nome_marca(self, nome: str) -> str:
        prefixos = ["Cerveja", "Chopp", "Vodka", "Whisky", "Gin", "Ice"]
        for p in prefixos:
            if nome.lower().startswith(p.lower()):
                return nome[len(p):].strip()
        return nome.strip()

    def dividir_em_blocos(self, event_map: Dict[str, Any], tamanho_bloco: int = 5):
        eventos = list(event_map.items())
        for i in range(0, len(eventos), tamanho_bloco):
            yield dict(eventos[i:i + tamanho_bloco])

    def processar_eventos(self, event_data: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
        resposta_formatada = {}

        for i, bloco in enumerate(self.dividir_em_blocos(event_data)):
            prompt_data = {event_id: data["event_description"] for event_id, data in bloco.items()}
            prompt = self.instruction + "\n\n" + json.dumps(prompt_data, ensure_ascii=False)

            try:
                response = self.client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant"},
                        {"role": "user", "content": prompt},
                    ],
                    stream=False
                )

                if response and response.choices:
                    raw_text = response.choices[0].message.content.strip()
                    json_start = raw_text.find("{")
                    json_end = raw_text.rfind("}") + 1
                    json_str = raw_text[json_start:json_end]
                    marcas_extraidas = json.loads(json_str)

                    for event_id, resultado in marcas_extraidas.items():
                        marcas = resultado.get("brands", [])
                        observacoes = resultado.get("observation", [])
                        resposta_formatada[event_id] = {
                            "brands": [
                                {
                                    "brand_id": self.brand_lookup.get(self.limpar_nome_marca(m)),
                                    "brand_name": self.limpar_nome_marca(m)
                                } for m in marcas
                            ],
                            "observation": observacoes
                        }


            except Exception as e:
                for event_id in bloco:
                    resposta_formatada[event_id] = {
                        "brands": [],
                        "observation": [f"Erro ao processar: {str(e)}"]
                    }

            time.sleep(1)

        return resposta_formatada

@app.post("/v1/brands")
def processar(request: EventMap):
    processor = DeepSeekProcessor(INSTRUCTION, client)
    try:
        return processor.processar_eventos(request.root)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
