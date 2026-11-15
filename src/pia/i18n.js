import {api} from './sdk.js';
let language='pt-BR',catalog={};
export function translate(text){return catalog[text]||text;}
function visit(node){
 if(node.nodeType===Node.TEXT_NODE){
  if(node.parentElement?.closest('textarea,input,pre,code,[data-i18n-skip],.message .markdown,.editor,.log,script,style'))return;
  const text=node.textContent,key=text.trim();if(!key)return;
  if(catalog[key]&&catalog[key]!==key)node.textContent=text.replace(key,catalog[key]);return;
 }
 if(node.nodeType!==Node.ELEMENT_NODE&&node.nodeType!==Node.DOCUMENT_NODE)return;
 if(node.nodeType===Node.ELEMENT_NODE){
  if(node.closest('[data-i18n-skip]'))return;
  for(const attr of ['title','aria-label','placeholder','data-tooltip']){
   const value=node.getAttribute(attr);if(value&&catalog[value]&&catalog[value]!==value)node.setAttribute(attr,catalog[value]);
  }
 }
 for(const child of node.childNodes)visit(child);
}
export async function initializeLanguage(){
 const prefs=await api('/preferences');language=prefs.language||'pt-BR';
 const response=await fetch('/pia/lang/'+language+'.json');if(!response.ok)throw Error('Idioma indisponível.');catalog=await response.json();document.documentElement.lang=language;visit(document.body);
 new MutationObserver(records=>{for(const record of records){if(record.type==='childList')for(const node of record.addedNodes)visit(node);else if(record.type==='characterData')visit(record.target);else if(record.type==='attributes')visit(record.target);}}).observe(document.body,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['title','aria-label','placeholder','data-tooltip']});
}
