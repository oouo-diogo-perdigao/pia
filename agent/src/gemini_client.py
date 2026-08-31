from __future__ import annotations

import json

from google import genai
from google.genai import types

from .config import (
    Settings,
    GEMINI_API_KEY,
    GEMINI_STT_MODEL,
    GEMINI_AGENT_MODEL,
    USER_NAME,
)
from .models import AgentDecision


class GeminiService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = genai.Client(api_key=GEMINI_API_KEY)

    def transcribe(self, wav_bytes: bytes) -> str:
        if not wav_bytes:
            return ""

        response = self.client.models.generate_content(
            model=GEMINI_STT_MODEL,
            contents=[
                (
                    "Transcreva somente a fala deste áudio em português do Brasil. "
                    "Não explique, não responda à fala e não adicione aspas. "
                    "Preserve nomes próprios e URLs quando forem pronunciados."
                ),
                types.Part.from_bytes(
                    data=wav_bytes,
                    mime_type="audio/wav",
                ),
            ],
            config=types.GenerateContentConfig(
                temperature=0,
            ),
        )

        return (response.text or "").strip().strip('"')

    def decide(self, utterance: str, memory_context: dict) -> AgentDecision:
        prompt = self._build_router_prompt(utterance, memory_context)

        interaction = self.client.interactions.create(
            model=GEMINI_AGENT_MODEL,
            input=prompt,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": AgentDecision.model_json_schema(),
            },
        )

        return AgentDecision.model_validate_json(interaction.output_text)

    def compose_tool_response(
        self,
        utterance: str,
        tool_results: list[dict],
        memory_context: dict,
    ) -> str:
        response = self.client.models.generate_content(
            model=GEMINI_AGENT_MODEL,
            contents=[
                (
                    "Responda em português do Brasil, em uma ou duas frases curtas, "
                    "para ser lido em voz alta. Baseie-se somente nos resultados das "
                    "ferramentas fornecidos. Não invente dados ausentes.\n\n"
                    f"Pedido do usuário: {utterance}\n"
                    f"Resultados: {json.dumps(tool_results, ensure_ascii=False)}\n"
                    f"Memória relevante: {json.dumps(memory_context, ensure_ascii=False)}"
                )
            ],
            config=types.GenerateContentConfig(
                temperature=0.2,
            ),
        )
        return (response.text or "").strip()

    def build_capability_prompt(
        self,
        utterance: str,
        description: str,
        proposed_tool_name: str | None,
    ) -> str:
        tool_name = proposed_tool_name or "nova_ferramenta"

        return f"""# Nova capacidade para o Voice Agent

## Solicitação original
{utterance}

## Capacidade ausente
{description}

## Nome de ferramenta sugerido
{tool_name}

## Objetivo
Implemente esta capacidade no projeto atual sem permitir execução arbitrária de shell gerado pela LLM.
A nova capacidade deve ser explícita, validada e registrada no roteador/executor existente.

## Arquitetura atual relevante
- `src/models.py`: enum/schema das ações permitidas.
- `src/actions.py`: executor local das ações.
- `src/gemini_client.py`: instruções do roteador Gemini.
- `src/agent.py`: orquestração, memória e aprendizado.
- `data/memory.json`: memória persistente; não usar `exec` para código vindo da IA.

## Requisitos
1. Adicione o menor handler explícito necessário.
2. Valide parâmetros antes da execução.
3. Não use `shell=True` com conteúdo fornecido pelo modelo.
4. Não execute a nova capacidade automaticamente durante a implementação.
5. Adicione um teste quando a lógica puder ser testada sem depender da UI do Windows.
6. Preserve o fluxo de aprendizado existente.
7. Depois da implementação, atualize as instruções do roteador para que o Gemini saiba quando usar a nova ação.

## Antes de alterar
Leia os arquivos relevantes e proponha a mudança mínima segura. Em seguida implemente e valide sintaxe/testes.
"""

    def _build_router_prompt(self, utterance: str, memory_context: dict) -> str:
        memory_json = json.dumps(memory_context, ensure_ascii=False, indent=2)

        return f"""Você é o roteador de um agente de voz local do Windows.
O usuário se chama {USER_NAME}.

Sua função é decidir se o pedido deve:
1. executar uma ou mais ações locais permitidas;
2. ser respondido verbalmente;
3. iniciar aprendizado de MEMÓRIA, quando a capacidade já existe mas falta um alvo específico;
4. iniciar aprendizado de CAPACIDADE, quando não existe ferramenta local capaz de executar a ação.

AÇÕES LOCAIS PERMITIDAS:
- delete_all: Ctrl+A e Backspace no aplicativo ativo.
- press_enter: pressiona Enter.
- open_url: abre uma URL HTTP/HTTPS conhecida com segurança.
- open_target: abre um programa por nome usando a pesquisa do menu Iniciar ou um caminho local conhecido.
- weather: consulta previsão meteorológica via API externa. Use `location` e `when` (`hoje`, `amanhã` ou YYYY-MM-DD).
- learned_action: executa uma ação previamente ensinada; use exatamente o `action_id` presente na memória.
- remember_fact: grava uma informação textual persistente em `facts` quando o usuário explicitamente pedir para lembrar de algo.

REGRAS IMPORTANTES:
- Nunca gere PowerShell, CMD, Python, shell ou código para execução direta.
- Nunca invente IDs de learned_action.
- Pode retornar várias ações em `actions`, na ordem necessária.
- Se for uma pergunta comum que não exige dado externo atual, use mode=answer e coloque a resposta curta em `spoken_response`.
- Para perguntas de clima, use a ação weather. A resposta final será formulada depois com o resultado real da API.
- Se a solicitação for abrir um site comum cujo domínio canônico é inequívoco, como YouTube, GitHub ou Gmail, você pode usar open_url.
- Se a solicitação for abrir um recurso PARTICULAR dentro de um site, canal, vídeo, jogo transmitido, página específica ou URL que NÃO esteja na memória, NÃO invente a URL. Use mode=learn_memory, learning.kind=url.
- Exemplo obrigatório: "Abre o jogo do roque no youtube" sem memória correspondente deve resultar em learn_memory. O prompt deve pedir para o usuário copiar o link correto e depois dizer "Pronto".
- Em learn_memory, `canonical_trigger` deve representar a intenção que será lembrada. `success_message` deve ser uma frase natural para usar depois que o usuário disser "Pronto" e a memória for salva.
- Em learn_memory, `success_message` deve mencionar {USER_NAME}, dizer que agora aprendeu a ação e indicar que vai executá-la imediatamente.
- Se o usuário pedir uma operação de computador para a qual não existe ação local permitida, use mode=learn_capability e learning.kind=capability. Exemplo: alterar o volume do Windows, se não houver ferramenta de volume.
- Para learn_capability, diga em `spoken_response` algo equivalente a: "Eu não sei executar essa ação, mas preparei o que é necessário para me ensinar no VS Code."
- Não transforme perguntas em ações desnecessárias.

MEMÓRIA ATUAL:
{memory_json}

PEDIDO DO USUÁRIO:
{utterance}
"""
