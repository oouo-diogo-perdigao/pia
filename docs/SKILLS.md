# Skills PIA

As skills são projetos Python em `Plugins/Skills/<projeto>/`. Integrações de navegador ficam em `Plugins/Browser/<projeto>/`, sem serem importadas pelo servidor. Cada projeto pode ter seu próprio repositório Git e ambiente uv para desenvolvimento. A PIA não cria repositórios nem instala dependências automaticamente.

## Estrutura

```text
Plugins/
  Skills/
    exemplo/
      plugin.toml
      plugin.py
      pyproject.toml
      README.md
      .gitignore
      example.png
    modo_ditado/
    previsao_do_tempo/
    abrir_bloco_de_notas/
    abrir_navegador/
    aprender_novo_comando/
  Browser/
    isekai0/
      isekai0.user.js
      package.json
      README.md
```

Copie `Plugins/Skills/exemplo` para uma pasta nova. Altere o `id` e as frases em `plugin.toml`:

```toml
id = "minha_skill"
commands = ["minha skill", "outro nome"]
entrypoint = "plugin.py"
enabled = true
```

Diga **comando recarregar skills** ou reinicie a PIA. Para desativar, configure `enabled = false` e recarregue. Ative com **comando minha skill**. Acentos e maiúsculas na frase são normalizados. Manifestos inválidos são registrados no log e não impedem carregar os demais projetos. Não coloque dependências/segredos no código; use `.env` local e arquivos ignorados pelo Git.

## Função execute

```python
def execute(piaTTS, piaSTT, piaClose):
    piaTTS("Diga algo ou finalizar.")
    def receber(texto):
        piaTTS("Você disse: " + texto)
    piaSTT(receber)
```

A PIA injeta funções por **nome do parâmetro**. Declare somente as necessárias, preferencialmente como parâmetros keyword-only (`def execute(*, piaTTS, piaSTT): ...`). `execute` é uma função Python síncrona, executada em uma thread da skill. Imports relativos como `from .weather import get_weather` funcionam dentro do projeto.

| API | Comportamento |
| --- | --- |
| `piaClose()` | Encerra a interação, limpa listeners/efeitos e cancela o áudio dessa skill. Não fecha o servidor/tray. |
| `piaSTT(callback)` | Registra um listener `callback(texto)` e mantém a sessão aberta. Retorna uma função para remover o listener. Um listener por skill; registrar outro substitui o anterior. |
| `piaTTS(texto, voice=None, speed=None)` | Enfileira uma fala e retorna um `concurrent.futures.Future`, concluído **depois da reprodução**, não ao enfileirar. Erros encerram a skill. |
| `piaInterface(acao, enabled=True)` | `blink`, `look`, `look_left`, `look_right`, `center`, `thinking`, `processing`, `pulse`. Efeitos ativos são desfeitos no encerramento. Operações chegam à thread Qt por sinal. |
| `piaView(imagem)` | Abre imagem local validada no visualizador do Windows, ou URL HTTP(S) no navegador. Caminhos relativos devem ser resolvidos a partir de `__file__` da skill. |
| `piaInsert(texto)` | Insere texto no cursor pela ação local da PIA. |
| `piaKey(*teclas)` | Pressiona uma tecla ou atalho, por exemplo `piaKey('ctrl', 'a')`. |
| `piaCancelled` | `threading.Event` para tarefas longas verificarem cancelamento cooperativo. |

## Ciclo de vida

Uma skill simples encerra automaticamente quando `execute` retorna. Se há falas pendentes, a interação fica aberta até a **última reprodução** terminar. Um listener mantém a sessão aberta para novas frases. Não chame `piaClose` imediatamente depois de `piaTTS` se deseja ouvir a fala inteira: `piaClose` é cancelamento imediato.

Exemplo: previsão consulta a API, enfileira a fala e retorna; a PIA só fecha a interação quando a fala termina. Ditado registra um listener e insere os textos subsequentes no cursor. `finalizar`, `encerrar` e as variantes de encerramento são interceptados antes do listener; nunca são digitados. A wake word de cancelamento e o clique de encerramento na interface continuam finalizando a sessão. Ao falar, a skill não recebe as transcrições enquanto seu próprio TTS está pendente, evitando autoalimentação; o encerramento continua tendo prioridade.

Somente uma skill fica ativa por interação. Operações de rede de uma skill devem ter timeout e tarefas longas devem verificar `piaCancelled`. A PIA não mata threads Python à força: o cancelamento impede novas ações pelas APIs, mas código externo já iniciado pode precisar de cleanup próprio. Executáveis abertos por uma skill não são fechados automaticamente.

## Dependências e Git

Os plugins executam no ambiente da PIA, com namespace de módulos separado por projeto, **sem sandbox e sem um interpretador separado**. Instale no ambiente da PIA as dependências extras do plugin usando uv; seu `pyproject.toml` também permite testes independentes com mocks das APIs. Instale apenas código em que confia.

O `.gitignore` da raiz ignora projetos adicionais em `Plugins/Skills/*` e `Plugins/Browser/*`, e inclui explicitamente os exemplos distribuídos. Assim um projeto pessoal pode ter seu próprio Git sem entrar no repositório da PIA. Para distribuir uma skill junto da PIA, acrescente uma exceção no `.gitignore`. As pastas distribuídas também possuem `.gitignore` para `.venv`, caches e segredos.

Não inicialize outro Git dentro dos exemplos já versionados sem antes separar o projeto do controle do repositório principal. Para criar um repositório independente, use uma pasta nova ignorada e inicialize o Git nela.

## Migração

`src/commands/*.py` foi substituído por projetos em `Plugins/Skills`. O userscript antigo `Plugins/isekai0.js` fica agora em `Plugins/Browser/isekai0/isekai0.user.js`, com lógica preservada. Atualize referências externas a esse caminho; instalações já importadas no Tampermonkey não dependem do local do arquivo.

A skill de aprendizado cria um scaffold pessoal após perguntar o nome; não gera código arbitrário pela LLM. Edite o projeto e recarregue as skills para ativá-lo.

## Testes offline

```powershell
uv run python -m pytest tests/test_skills.py -q
```

Os testes usam stubs para programas, teclado, rede e reprodução. Não executam ações reais no desktop.
