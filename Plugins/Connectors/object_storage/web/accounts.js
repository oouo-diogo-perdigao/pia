import {session,api,appApi,element as el} from '/pia/sdk.js';
import {iconButton,alertError,armDelete,passwordField} from '/pia/ui.js';
const $=s=>document.querySelector(s),form=$('#account-form'),call=(action,data={})=>appApi('object_storage',action,data);
for(const key of ['access_key','secret_key','session_token'])passwordField(form.elements[key]);
async function load(){
 const {accounts}=await call('accounts');$('#account-list').replaceChildren();
 for(const account of accounts){
  const row=el('div',undefined,'row');row.append(el('span',account.name+' · '+(account.endpoint||'AWS')));
  if(account.id!=='legacy')row.append(iconButton('edit','Editar conta',async()=>{
   for(const key of ['id','name','provider','endpoint','region','bucket','public_url'])form.elements[key].value=account[key]||'';
   const secrets=await api('/integrations/object_storage/secrets',{account:account.id});
   for(const key of ['access_key','secret_key','session_token'])form.elements[key].value=secrets[key];
  }),iconButton('delete','Remover conexão',async(event,button)=>{if(!armDelete(button))return;await call('remove-account',{id:account.id});await load();}));
  $('#account-list').append(row);
 }
}
form.onsubmit=async event=>{event.preventDefault();try{const data=Object.fromEntries(new FormData(form));data.default=form.elements.default.checked;await call('save-account',data);form.reset();await load();}catch(error){alertError(error);}};
$('#new-account').onclick=()=>form.reset();await session();await load();
