# Interface, configurações e extensões

A janela usa HTML/CSS/JavaScript. O menu **Exibir → Inspecionar HTML / CSS / JS** e a tecla **F12** abrem o DevTools do Chromium incorporado, com DOM, estilos, console e rede. Ao acessar `http://localhost:8762/` em um navegador, use o inspetor do próprio navegador.

## Organização

- `src/pia/`: interface geral; `src/pia/lang/pt-BR.json` e `en.json`: traduções.
- `src/piamini/`: Mini PIA.
- `config/settings.schema.json`: schema nativo; valores no SQLite do perfil.
- `Plugins/Apps/`: aplicativos com páginas Principal e Sobre; valores pessoais no SQLite.
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

## Configuração interna e perfil

Declare `settings.schema.json` no plugin com campos `name`, `type`, `default`, `label` e `link`. Tipos: bool, int, float, path, file, secret e string. Todos aceitam vazio. Não há `.env` nem configuração por ambiente. Valores ficam no SQLite; credenciais no cofre, com referências no banco. Use `src.settings_store` para ler/salvar e `src.user_paths.user_path` para os dados pessoais.

Arquivos de configuração comuns ficam em Documentos/pia/files; arquivos de credenciais são guardados em bytes no cofre. Pastas de saída padrão são resolvidas pelo sistema e não têm overrides por app. Apps oferecem configuração pela interface compartilhada; contas continuam nos conectores. O editor de documentos nativos mantém atalhos, catálogo e palavras de ativação no SQLite.

Veja [Perfil e migração](PROFILE_MIGRATION.md) para exemplos de API, backup criptografado e importação entre Windows/Linux. As regras antigas de sufixos e dotenv existem somente para a migração inicial de instalações anteriores.

## Verificação local

```powershell
$env:PYTHONPATH='.;Plugins/Apps/podcast_automation/src'
.venv/Scripts/python.exe -m pytest tests Plugins/Apps/podcast_automation/tests -q
.venv/Scripts/python.exe tests/desktop_smoke.py
```

O teste gráfico usa áudio, imagens e provedores sintéticos. Não captura a tela real nem acessa contas Google, Discord ou buckets reais.


A interface atual usa React/Mantine. Consulte [Workspace React e progresso do podcast](REACT_WORKSPACE.md) para o build, navegação, cache, reinício e transcrição local medium.
