# Plugin Object Storage

Integra contas Amazon S3, Cloudflare R2 e outros serviços compatíveis com S3. A interface está no app `Plugins/Apps/object_storage`; as contas, credenciais e operações compartilhadas ficam neste plugin.

Cadastre várias conexões na interface do app ou em Configurações → Plugins · object_storage → Gerenciar contas. Metadados ficam em `config.json`; novas chaves ficam no cofre do sistema. A conta migrada usa o `.env` local deste plugin. Região `auto` é apropriada para R2; AWS usa sua região real (ou us-east-1 quando não configurada).

API Python: `ObjectStorage().accounts()`, `.client(account)`, `.list(account, bucket, prefix, cursor)`, `.upload(path,key,account,bucket)`, `.get(...)`, `.put(...)`, `.copy(...,move=True)`, `.delete(keys,account,bucket)` e `.public_url(key,account)`. Transferências usam boto3 e uploads multipart gerenciados. Cópia entre contas faz streaming pelo computador; mover só exclui a origem depois do envio terminar.

Skills: `piaPlugins('object_storage','accounts.list')` e `piaPlugins('object_storage','files.list',account='ID',bucket='bucket',prefix='pasta/')`. O app fornece as operações de escrita. Para novos recursos, amplie este plugin; não copie autenticação para cada app.

Dependência: boto3 (instalada com a PIA). Referências: [S3/Boto3](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html), [credenciais R2](https://developers.cloudflare.com/r2/api/s3/tokens/).


## Manifesto e idioma

Os metadados desta extensão ficam em `pia.json` e os textos em `lang/pt-BR.json`. Consulte o [padrão de extensões e variáveis tipadas](../../../docs/EXTENSIONS.md) para criar telas, campos de configuração e integrações compartilhadas.
