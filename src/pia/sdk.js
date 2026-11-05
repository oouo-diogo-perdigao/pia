// Standard same-origin API used by the workspace and every app HTML page.
export async function session(){const r=await fetch('/api/pia/session',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(!r.ok)throw Error('Não foi possível iniciar a sessão local.');}
export async function api(path,data){const r=await fetch('/api/pia'+path,{method:data===undefined?'GET':'POST',headers:data===undefined?{}:{'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});const result=await r.json();if(!r.ok)throw Error(result.error||'Falha na solicitação.');return result;}
export function watchJob(id,onEvent){const stream=new EventSource('/api/pia/events/'+id);stream.onmessage=e=>{const value=JSON.parse(e.data);onEvent(value);if(value.type==='done'||value.type==='error')stream.close();};return stream;}
export function appApi(id,action,payload={}){return api('/apps/'+id+'/'+action,payload);}
export function settingsLink(section){parent.postMessage({type:'pia:settings',section},location.origin);}
export function publishNotification(appId,title,text,links=[]){return api('/notifications/publish',{source:'Apps/'+appId,title,text,links});}
export async function playMedia(url,title){return (await import('./media.js')).playMedia(url,title);}
export async function pauseMedia(){return (await import('./media.js')).pauseMedia();}
export function element(tag,text,className){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;}
