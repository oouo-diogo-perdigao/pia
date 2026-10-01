import os
import yaml
import litellm
from litellm import Router
from pathlib import Path
import warnings

from ..config import logging
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

# Inicializa o Roteador de LLMs carregando as prioridades e fallbacks do YAML
os.environ["LITELLM_LOG"] = "ERROR"
# Suprime os avisos internos do LiteLLM sobre custos de modelos
litellm.suppress_debug_info = True
warnings.filterwarnings("ignore", category=UserWarning, module="litellm")


CONFIG_PATH = BASE_DIR / "models.yaml"

config_data = {}
if CONFIG_PATH.exists():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f) or {}
else:
    logging.warning("[ROUTER] Arquivo 'models.yaml' não encontrado em: %s", CONFIG_PATH)


llm_router = Router(
    model_list=config_data.get("model_list", []),
    **config_data.get("router_settings", {}),
)


# ============================================================================
# GERENCIADOR DE AGENTES COM LITELLM ROUTER
# ============================================================================
class GenericAgent:
    """Agente genérico que consome a lista de prioridades do Router."""

    def run(self, prompt: str) -> str:
        # Mostra a entrada na tela
        print(f"\n[AGENT INPUT]: {prompt}")

        messages = [
            {
                "role": "system",
                "content": (
                    "Você é uma assistente inteligente, prestativa e sucinta. "
                    "Responda de forma direta em português."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]

        # O Router recebe o alias configurado no models.yaml e decide
        # qual modelo utilizar, aplicando os fallbacks configurados.
        response = llm_router.completion(
            model="auto-agent",
            messages=messages,
        )

        # Somente depois da resposta podemos descobrir qual modelo
        # efetivamente foi utilizado.
        used_model = getattr(response, "model", "desconhecido")

        logging.info(
            "[ROUTER] Resposta gerada usando o modelo: %s",
            used_model,
        )

        answer = response.choices[0].message.content

        # Mostra a saída completa na tela
        print(f"[AGENT OUTPUT]: {answer}\n")

        return answer

    def run_stream(self, prompt: str):
        # Mostra a entrada na tela
        print(f"\n[AGENT STREAM INPUT]: {prompt}")
        print("[AGENT STREAM OUTPUT]: ", end="", flush=True)

        messages = [
            {
                "role": "system",
                "content": "Você é uma assistente inteligente, prestativa e sucinta. Responda de forma direta em português.",
            },
            {"role": "user", "content": prompt},
        ]
        # Ativa o stream no router/litellm
        response = llm_router.completion(
            model="auto-agent", messages=messages, stream=True
        )

        full_response = ""
        for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                # Imprime cada pedaço na tela em tempo real conforme é gerado
                print(delta, end="", flush=True)
                full_response += delta
                yield delta

        print("\n")  # Quebra de linha ao finalizar o stream
