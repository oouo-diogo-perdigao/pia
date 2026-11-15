# PIA Server

Na PIA desktop, escolha **Continuar com Google** e abra o login no navegador. Confira o código e autorize o computador. A PIA libera o workspace automaticamente e guarda a sessão no cofre do sistema. Em **Configurações → Conectores → PIA Server**, escolha as ações que o servidor pode executar. Câmera e captura de tela ficam desativadas por padrão. A PIA desktop deve estar aberta no computador escolhido.

O computador faz conexões de saída por HTTPS. As capturas solicitadas pelo MCP são guardadas na pasta privada da conta no Drive. Cada computador tem uma sessão própria. Encerre a sessão no desktop ou revogue o computador pelo painel da PIA Server.

Em **Sincronização automática**, acompanhe o estado da sincronização. Ela inicia com a conexão e reconcilia configurações compartilhadas, preferências da interface e conversas em segundo plano. O servidor guarda o perfil criptografado. O cliente compara mudanças por registro, preserva itens independentes e tenta novamente quando a rede cai. Na primeira conexão, um item já existente no servidor prevalece sobre o mesmo item local. Depois, conflitos simultâneos no mesmo campo favorecem a mudança local do computador que reconcilia a revisão. Rascunhos, permissões, caminhos externos e preferências de notificação pertencem ao computador.

Ative a **Secretária** no painel web e habilite **Receber avisos da Secretária do servidor neste computador** no conector desktop. Isso troca o monitoramento local pelo recebimento da fila remota. As preferências de exibição e leitura continuam na central de notificações local.

Novas capturas salvas e músicas geradas enquanto o computador tem uma sessão da PIA Server entram automaticamente na fila de cópia para o Drive da conta. O desktop mantém o original e tenta novamente quando o Drive está indisponível. Essa fila envia cópias novas. Arquivos anteriores e downloads de mídia em outros computadores ficam fora desse fluxo.
