# 0003 — Perfil do usuário, SQLite e cofre

Status: Aceita.

## Contexto

Configurações e credenciais na instalação dificultavam migração Windows/Linux.

## Decisão

Configurações são gerenciadas pela interface e persistidas no SQLite em Documentos/pia. Credenciais ficam no cofre do sistema. Schemas versionados descrevem campos sem segredos. Dados persistentes usam o perfil; cache, logs e ambiente Python permanecem na instalação. O launcher importa arquivos antigos uma vez.

A exportação usa AES-GCM e chave derivada por Scrypt quando o usuário informa uma senha. Com a senha em branco, o backup fica em texto legível. Inclui configurações e entradas lógicas do cofre. Histórico e mídia ficam fora desse arquivo.

## Consequências

O cofre precisa estar disponível e desbloqueado. Não existe transação distribuída entre SQLite e cofre; fontes ainda não confirmadas são preservadas em falhas. Alguns provedores podem exigir nova autenticação no destino.

Operação: [Perfil e migração](../PROFILE_MIGRATION.md).
