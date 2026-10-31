# Núcleo Python

Leia o [AGENTS.md da raiz](../AGENTS.md) e o mapa em [architecture.md](../docs/architecture.md). Estas regras complementam as gerais para `src/`.

- Reutilize managers e serviços existentes para STT, TTS, agentes e recursos. Não instancie motores pesados por requisição ou no import de um módulo que deveria ser leve.
- Mantenha separação entre serviço, transporte HTTP e integração Qt. Serviços usados pelo navegador e testes não devem exigir uma janela gráfica.
- Rotas novas precisam de validação, limites e autenticação apropriada; não confie apenas no endereço loopback. Preserve contratos OpenAI e tokens internos de apps.
- Voz/streaming são concorrentes: respostas canceladas não podem voltar a enfileirar áudio. Preserve epochs e liberação de dispositivos/locks em falhas.
- Áudio longo exige duração e offsets reais, fallback e recuperação localizada; silêncio é válido. Não esconda falhas com timestamps artificiais ou truncamento silencioso.
- Use config_paths/env_types, registro comum de ferramentas e infraestrutura de jobs/logs. Regras de um plugin permanecem no plugin.
- Teste interfaces com stubs antes de usar hardware ou contas reais. Comandos estão em [testing.md](../docs/testing.md).
