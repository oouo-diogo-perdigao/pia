import {session,api} from '/pia/sdk.js';
import {iconButton,copyText,feedback,alertError,armDelete} from '/pia/ui.js';
const $=s=>document.querySelector(s),call=(action,data={})=>api('/integrations/discord/'+action,data);
let currentChannel=null,enabled=null;
async function logs(){const result=await call('logs');$('#logs').textContent=result.text||'Nenhum log do Discord.';}
async function refresh(){
 const result=await call('status');
 const labels={stopped:'Desconectado',connecting:'Conectando',connected:'Conectado · aguardando /link',reconnecting:'Reconectando',error:'Erro'};
 $('#status').textContent=(result.configured?'Token configurado':'Token não configurado')+' · '+(labels[result.gateway.state]||result.gateway.state)+(result.gateway.error?' · '+result.gateway.error:'');
 $('#binding').textContent=result.linked.channel?'Canal vinculado: '+(result.linked.name||result.linked.channel)+' · servidor '+result.linked.guild:'Nenhum vínculo criado por /link nesta PIA.';
 $('#channel-id').textContent=result.channel?'DISCORD_CHANNEL_ID='+result.channel:'DISCORD_CHANNEL_ID ainda não configurado';
 const changed=currentChannel!==result.channel;if(changed){$('#test-channel').value=result.channel;currentChannel=result.channel;}
 if(enabled!==result.link_enabled||changed){enabled=result.link_enabled;parent.postMessage({type:'pia:discord-config',channel:result.channel,enabled},location.origin);}
 $('#disconnect').disabled=!result.link_enabled;return result;
}
async function operation(button,fn){
 button.disabled=true;$('#result').textContent='Executando…';$('#result').classList.remove('error');
 try{const message=await fn();$('#result').textContent=message;await refresh();await logs();}
 catch(error){$('#result').textContent=error.message;$('#result').classList.add('error');alertError(error);await logs().catch(()=>{});$('#logs').scrollIntoView({behavior:'smooth',block:'nearest'});}
 finally{button.disabled=false;}
}
$('#diagnose').onclick=event=>operation(event.currentTarget,async()=>{const result=await call('diagnose',{channel:$('#test-channel').value.trim()});return 'Conexão válida: '+result.name+(result.channel?' · #'+result.channel.name+' ('+result.channel.id+')':' · nenhum canal selecionado');});
$('#test').onclick=event=>operation(event.currentTarget,async()=>{const result=await call('test',{channel:$('#test-channel').value.trim()});return 'Mensagem de teste enviada. Canal: '+result.channel+' · mensagem: '+result.id;});
$('#register').onclick=event=>operation(event.currentTarget,async()=>{await call('register-link');return '/link registrado. Aguarde a conexão e use /link no Discord. A propagação do comando pode levar alguns instantes.';});
$('#connect').onclick=event=>operation(event.currentTarget,async()=>{await call('listener',{enabled:true});return 'Conectando o bot à PIA local…';});
$('#disconnect').onclick=event=>operation(event.currentTarget,async()=>{await call('listener',{enabled:false});return 'Recebimento local de /link desativado. O envio de publicações continua disponível.';});
$('#binding-actions').append(iconButton('copy','Copiar DISCORD_CHANNEL_ID',async(event,button)=>{if(!currentChannel)throw Error('Nenhum canal configurado.');await copyText(currentChannel);feedback(button,'copy');}),iconButton('delete','Remover vínculo local',async(event,button)=>{if(!armDelete(button))return;await operation(button,async()=>{await call('unlink');return 'Vínculo removido. Use /link para escolher outro servidor/canal.';});}));
$('#log-actions').append(iconButton('retry','Atualizar log',logs),iconButton('copy','Copiar log',async(event,button)=>{await copyText($('#logs').textContent);feedback(button,'copy');}));
await session();await refresh();await logs();setInterval(()=>{if(!document.hidden)refresh().catch(alertError);},5000);
