# Plugin Google

## Drive compartilhado com apps

`drive.py` utiliza as contas OAuth autorizadas em **Conectores / Google**, compartilhadas com Gmail e Agenda. O podcast guarda apenas a conta e a pasta escolhidas no seu config.json. Não é necessário `GOOGLE_APPLICATION_CREDENTIALS__FILE`; arquivos antigos não são usados nem apagados. A pasta de gravações é escolhida no navegador de pastas do próprio podcast e deve ser confirmada em **Salvar opções**.

API: `Drive(resources).accounts()`, `.list(account,folder,folders_only,cursor,search)`, `.download(file_id,destination,account)` e `.rename(file_id,name,account)`. A listagem suporta paginação e drives compartilhados; download grava em arquivo temporário e só substitui o destino quando termina. Skills podem listar pastas com `piaPlugins('google','drive.folders',account='ID')`.

Para marcar gravações processadas, a conta OAuth precisa do escopo Drive de leitura e escrita. Contas autorizadas antes dessa mudança precisam ser reconectadas para conceder o novo escopo. Contas de serviço precisam de acesso à pasta, concedido ao client_email da credencial. [Arquivos e pastas no Drive](https://developers.google.com/workspace/drive/api/reference/rest/v3/files).


## Manifesto e idioma

Os metadados desta extensão ficam em `pia.json` e os textos em `lang/pt-BR.json`. Consulte o [padrão de extensões e variáveis tipadas](../../../docs/EXTENSIONS.md) para criar telas, campos de configuração e integrações compartilhadas.
