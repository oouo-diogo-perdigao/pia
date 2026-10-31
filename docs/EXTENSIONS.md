# Interface, configurações e extensões

A janela usa HTML/CSS/JavaScript. O menu **Exibir → Inspecionar HTML / CSS / JS** e a tecla **F12** abrem o DevTools do Chromium incorporado, com DOM, estilos, console e rede. Ao acessar `http://localhost:8762/` em um navegador, use o inspetor do próprio navegador.

## Organização

- `src/pia/`: interface geral; `src/pia/lang/pt-BR.json` e `en.json`: traduções.
- `src/piamini/`: Mini PIA.
- `config/.env`: configuração geral.
- `Plugins/Apps/`: aplicativos com páginas Principal e Sobre.
- `Plugins/Connectors/`: conexões compartilhadas com serviços e contas.
- `Plugins/Bot/`, `Skills/` e `Browser/`: bots, comandos e integrações de navegador.

Cada extensão contém `pia.json` e `lang/pt-BR.json`. O idioma geral é escolhido em **Configurações → Geral → Idioma**, salvo no banco local e aplicado após recarregar a interface. Português é o padrão. As páginas próprias das extensões permanecem em português nesta versão.

Exemplo de `pia.json` para aplicativo:

```json
{
  "nome": "Capturas de tela",
  "app_id": "screenshots",
  "info": "Selecione, anote, recorte e salve. Sem uploads e sem e-mail.",
  "type": "app",
  "home": "index.html",
  "about": "about.html",
  "lang": "lang/pt-BR.json"
}
```

`home` e `about` apontam para arquivos dentro de `web/`. O host usa o nome e a descrição do manifesto no cabeçalho e cria a navegação **Principal / Sobre**. `plugin.toml` continua definindo os pontos de entrada Python, voz e API. Os tipos são `app`, `connector`, `bot`, `skill` e `browser`. Não inclua segredos nesses manifestos ou nos arquivos de tradução.

As contas ficam em **Configurações → [conector]**, não no aplicativo que as consome. O Object Storage usa o cofre do sistema para credenciais de contas. Os segredos configurados aparecem em campos de senha com o tamanho real e um botão de olho. Eles só são fornecidos à sessão local autenticada e não são incluídos nos recursos públicos da interface.

## Variáveis tipadas

O tipo é um sufixo separado por dois sublinhados:

```dotenv
ENABLED__BOOL=true
PORT__INT=8762
TEMPERATURE__FLOAT=0.4
OUTPUT__PATH=
GOOGLE_APPLICATION_CREDENTIALS__FILE=
API_KEY__SECRET=
MODEL=meu-modelo
```

| Sufixo | Interface e validação |
| --- | --- |
| `__BOOL` | Seletor `true`, `false` ou vazio; outros valores são rejeitados. |
| `__INT` | Inteiro, sem casas decimais. |
| `__FLOAT` | Número finito; `NaN` e infinito são rejeitados. |
| `__PATH` | Caminho existente, com seletores nativos de pasta ou arquivo externo. |
| `__FILE` | Arquivo existente; permite carregar uma cópia gerenciada ou selecionar um arquivo externo. |
| `__SECRET` | Senha com botão de mostrar/ocultar. |
| Sem sufixo / `__STRING` | Texto livre. |

Todos aceitam vazio. Apagar um segredo e salvar limpa o valor. Campos numéricos e booleanos vazios usam os padrões do programa no próximo início. A aplicação valida todos os valores enviados antes de gravar a seção. Salvar solicita reinício pelo launcher, aguardando jobs em execução; uma instância sem sessão gráfica informa a limitação. Veja [o fluxo de reinício](REACT_WORKSPACE.md).

Os consumidores Python usam `src.env_types.load_dotenv` ou `dotenv_values`: uma chave `PORT__INT` é entregue ao código como `PORT`. Os nomes antigos continuam aceitos. O editor apresenta o tipo declarado em `.env.example` também para um valor legado e, ao salvar, substitui sua chave antiga pela tipada. Variáveis desconhecidas sem tipo mantêm o comportamento de texto.

Uploads têm limite de **5 MiB** e ficam na subpasta privada `files/` junto ao `.env` da respectiva seção. O nome é `<app-ou-conector>_<VARIAVEL>.<extensão>`, por exemplo `google_GOOGLE_APPLICATION_CREDENTIALS.json`. O caminho é salvo automaticamente no `.env`. O botão de pasta abre o diretório do arquivo. Arquivos selecionados pelo caminho externo não são copiados.

O exemplo FILE acima ilustra o tipo de campo, não uma exigência do Podcast Automation. Para o fluxo atual do podcast, conecte a conta pelo conector Google e selecione a pasta no app. Não recrie GOOGLE_APPLICATION_CREDENTIALS ou GOOGLE_DRIVE_FOLDER_ID no app: ele usa as contas e o seletor de pastas da integração compartilhada. A lista contém somente pastas acessíveis à conta escolhida.

Na atualização da antiga pasta `Plugins/Plugins`, a migração preserva configurações locais ignoradas pelo Git copiando as ausentes para `Plugins/Connectors`, sem sobrescrever destinos existentes.

## Verificação local

```powershell
$env:PYTHONPATH='.;Plugins/Apps/podcast_automation/src'
.venv/Scripts/python.exe -m pytest tests Plugins/Apps/podcast_automation/tests -q
.venv/Scripts/python.exe tests/desktop_smoke.py
```

O teste gráfico usa áudio, imagens e provedores sintéticos. Não captura a tela real nem acessa contas Google, Discord ou buckets reais.


A interface atual usa React/Mantine. Consulte [Workspace React e progresso do podcast](REACT_WORKSPACE.md) para o build, navegação, cache, reinício e transcrição local medium.
