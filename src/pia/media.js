// Shared PIA player. Apps use this API instead of owning independent audio tags.
import {api} from './sdk.js';
const audio=new Audio();audio.preload='none';
const client=crypto.randomUUID();let title='',timer;const listeners=new Set();
function active(){return !audio.paused&&!audio.ended&&!audio.error;}
export function mediaSnapshot(){return {url:audio.getAttribute('src')||'',title,playing:active(),current:audio.currentTime||0,duration:Number.isFinite(audio.duration)?audio.duration:0};}
function changed(){for(const listener of listeners)listener(mediaSnapshot());}
function reportState(){return api('/media/state',{client,playing:active()}).catch(()=>{});}
function playback(){clearInterval(timer);reportState();if(active())timer=setInterval(reportState,5000);changed();}
for(const event of ['play','pause','ended','error'])audio.addEventListener(event,playback);
for(const event of ['timeupdate','loadedmetadata'])audio.addEventListener(event,changed);
export function subscribeMedia(listener){listeners.add(listener);listener(mediaSnapshot());return()=>listeners.delete(listener);}
export async function playMedia(url,label='Música'){
  const source=new URL(url,location.origin);
  if(source.origin!==location.origin||!source.pathname.startsWith('/api/pia/'))throw Error('Use um recurso de áudio local autenticado da PIA.');
  title=label;if(audio.src!==source.href)audio.src=source.href;
  await audio.play();changed();
}
export function pauseMedia(){audio.pause();}
export function seekMedia(value){if(Number.isFinite(value))audio.currentTime=Math.max(0,Math.min(value,audio.duration||0));}
export function stopMedia(){audio.pause();audio.removeAttribute('src');audio.load();title='';changed();}
window.addEventListener('pagehide',()=>{clearInterval(timer);fetch('/api/pia/media/state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({client,playing:false}),keepalive:true});});
