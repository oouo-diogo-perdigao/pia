"""Outbound-only Discord Gateway lifecycle. No public HTTP endpoint required."""
import asyncio
import threading
from .service import Discord


class DiscordRuntime:
    def __init__(self, bot=None):
        self.bot = bot or Discord()
        self.lock = threading.RLock()
        self.thread = None
        self.loop = self.client = None
        self.stopping = threading.Event()
        self.state, self.error = 'stopped', ''
        self.seen = set()

    def status(self):
        with self.lock:
            return dict(state=self.state, error=self.error, running=bool(self.thread and self.thread.is_alive()))

    def start_if_enabled(self):
        try:
            if self.bot.public()['link_enabled']:
                self.start()
        except Exception as exc:
            self.fail(exc)

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return self.status()
            if not self.bot.public()['link_enabled']:
                return self.status()
            self.stopping.clear()
            self.state, self.error = 'connecting', ''
            self.thread = threading.Thread(target=self._run, daemon=True, name='pia-discord')
            self.thread.start()
            return self.status()

    def stop(self):
        self.stopping.set()
        loop, client = self.loop, self.client
        if loop and client and loop.is_running():
            asyncio.run_coroutine_threadsafe(client.close(), loop)

    def restart(self):
        self.stop()
        thread = self.thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=8)
            if thread.is_alive():
                raise RuntimeError('A conexão anterior do Discord ainda está encerrando. Tente novamente.')
        return self.start()

    def fail(self, error):
        with self.lock:
            self.error = self.bot.clean(str(error))
            self.state = 'error'
        self.bot.log('Gateway: ' + self.error, error=True)

    async def interaction(self, interaction):
        if interaction.type.value != 2 or (interaction.data or {}).get('name') != 'link':
            return
        identity = str(interaction.id)
        if identity in self.seen:
            return
        self.seen.add(identity)
        if len(self.seen) > 2000:
            self.seen = {identity}
        try:
            # Acknowledge within Discord's deadline; all confirmations/errors are private.
            await interaction.response.defer(ephemeral=True, thinking=True)
            result = await asyncio.to_thread(self.bot.link,
                guild=interaction.guild_id, channel=interaction.channel_id, user=interaction.user.id,
                permissions=interaction.permissions.value, app_permissions=interaction.app_permissions.value,
                application=interaction.application_id)
            text = result['text']
        except Exception as exc:
            text = self.bot.clean(str(exc)).replace(interaction.token, '[REDACTED]')
            self.bot.log('/link rejeitado/falhou: ' + text, error=True)
        try:
            import discord
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            else:
                await interaction.response.send_message(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        except Exception as exc:
            self.bot.log('Falha ao responder /link: ' + self.bot.clean(str(exc)).replace(interaction.token, '[REDACTED]'), error=True)

    async def _serve(self):
        import discord
        runtime = self

        class Client(discord.Client):
            async def on_ready(self):
                runtime.state, runtime.error = 'connected', ''
                runtime.bot.log(f'Gateway conectado: bot={self.user.id}. Aguardando /link de administradores.')

            async def on_disconnect(self):
                if not runtime.stopping.is_set():
                    runtime.state = 'reconnecting'

            async def on_interaction(self, interaction):
                await runtime.interaction(interaction)

            async def on_error(self, event, *args, **kwargs):
                # Never log event arguments: interactions contain continuation tokens.
                runtime.bot.log('Erro no evento Gateway: ' + event, error=True)

        self.loop = asyncio.get_running_loop()
        async with Client(intents=discord.Intents.none(), max_messages=None) as client:
            self.client = client
            if not self.stopping.is_set():
                await client.start(self.bot.config().get('DISCORD_BOT_TOKEN', ''), reconnect=True)

    def _run(self):
        try:
            asyncio.run(self._serve())
        except ImportError:
            self.fail('Instale a dependência discord.py: execute novamente install.sh.')
        except Exception as exc:
            self.fail(exc)
        finally:
            self.loop = self.client = None
            if self.state != 'error' or self.stopping.is_set():
                self.state = 'stopped'


_runtime = None
_lock = threading.Lock()

def get_runtime():
    global _runtime
    with _lock:
        if _runtime is None:
            _runtime = DiscordRuntime()
        return _runtime
