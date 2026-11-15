# Configuração, contas e segredos

As configurações são editadas pela interface, armazenadas no SQLite do perfil e validadas pelos schemas versionados. As credenciais locais pertencem ao cofre do sistema. As credenciais dos conectores gerenciados na PIA Server ficam criptografadas no servidor. Não há .env nem overrides por variáveis de ambiente da PIA.

Consulte [Perfil, cofre e migração](PROFILE_MIGRATION.md) para caminhos Windows/Linux, atualização de instalações existentes, tipos e APIs de desenvolvimento.

Apps usam as contas dos conectores, explicitamente selecionadas. Não duplique chaves LLM/STT nem credenciais de Google/Discord/storage em apps. Os schemas e a implementação de cada extensão continuam em sua própria pasta; o estado pessoal não fica dentro da instalação.

Salvar só fica habilitado quando há mudanças e produz toast. Configurações que afetam serviços solicitam reinício, respeitando os jobs em andamento. Credenciais ficam mascaradas; arquivos de credenciais enviados vão ao cofre e não são publicados como assets. Se o cofre estiver indisponível, informe o erro sem fallback para texto.

Nunca registre valores secretos, cookies ou tokens em logs.
