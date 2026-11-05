# Configuração, contas e segredos

As configurações são editadas pela interface, armazenadas no SQLite do perfil e validadas pelos schemas versionados. Credenciais pertencem ao cofre seguro do sistema. Não há .env nem overrides por variáveis de ambiente da PIA.

Consulte [Perfil, cofre e migração](PROFILE_MIGRATION.md) para caminhos Windows/Linux, atualização de instalações existentes, exportação/importação por senha, tipos e APIs de desenvolvimento.

Apps usam as contas dos conectores, explicitamente selecionadas. Não duplique chaves LLM/STT nem credenciais de Google/Discord/storage em apps. Os schemas e a implementação de cada extensão continuam em sua própria pasta; o estado pessoal não fica dentro da instalação.

Salvar só fica habilitado quando há mudanças e produz toast. Configurações que afetam serviços solicitam reinício, respeitando os jobs em andamento. Credenciais ficam mascaradas; arquivos de credenciais enviados vão ao cofre e não são publicados como assets. Se o cofre estiver indisponível, informe o erro sem fallback para texto.

O backup criptografado inclui configurações, preferências, documentos lógicos, arquivos gerenciados e credenciais da PIA. Não inclui mídia, conversas, modelos ou logins externos do Codex/AGY. Nunca registre valores secretos, senhas de backup, cookies ou tokens em logs.
