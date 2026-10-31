# Desenvolvimento

Leia o AGENTS.md da raiz e os da área afetada. Preserve trabalho local existente; confira `git status` antes de editar. Não atualize dependências, reinstale modelos ou altere configurações pessoais sem necessidade da tarefa.

## Instalar e iniciar

Pré-requisitos Python e dependências estão em `pyproject.toml` (Python 3.12). O instalador usa uv e prepara as dependências de sistema conforme o ambiente.

No Linux ou no **Git Bash do Windows nativo**:

```sh
bash install.sh
bash start.sh
```

A instalação inicia a PIA por padrão; `bash install.sh --help` lista opções como `--dry-run` e `--no-start`. Não use uma instalação real para apenas verificar o script: ela pode baixar dependências, mudar autostart e iniciar áudio/UI.

No PowerShell, `bash.exe` pode ser o launcher do WSL. Confira `Get-Command bash`: se apontar para `C:\Windows\System32\bash.exe`, isso não seleciona Git Bash. Executar dentro do WSL instala para Linux, com implicações para áudio, câmera, bandeja e sessão gráfica. Use Git Bash para o desktop Windows nativo.

## Frontend

Node/npm são usados para desenvolvimento e build; não é necessário servidor Node em produção.

```sh
npm --prefix src/pia/frontend ci
npm --prefix src/pia/frontend test
npm --prefix src/pia/frontend run build
```

Edite JSX e estilos de origem, nunca o bundle. Inclua alterações geradas em `src/pia/assets/`. Acesse `http://localhost:8762/`; na janela nativa, F12 ou Exibir → Inspecionar HTML / CSS / JS abre DevTools.

## Python e verificação

Use `.venv/Scripts/python.exe` no Windows e `.venv/bin/python` no Linux. Dependências opcionais do podcast usam o extra `podcast`; as de desenvolvimento estão no grupo `dev`. Prefira o instalador/ambiente existente, respeitando versões de Torch/CUDA e requisitos do sistema. ACE-Step tem ambiente próprio: não misture suas dependências com as da PIA.

Comandos reproduzíveis e seleção de testes estão em [testing.md](testing.md). Ao reportar falhas, distinga regressão do código, dependência ausente e limitação do ambiente.

## Fluxo Git e documentação

Use a branch solicitada pelo usuário; para uma nova branch sem nome especificado, prefira `codex/<assunto>`. Não mude branch com trabalho local sem avaliar como preservá-lo. Commit/PR/push são feitos quando autorizados, sem merge automático.

Documente o comportamento final, não o histórico da conversa. Regras gerais pertencem ao AGENTS.md; operação e contratos aos docs/READMEs; decisões aos ADRs; pedidos pendentes a issues ou TODOs claramente identificados. Antes de citar um comando, confira que existe no repositório.
