let stream;
function startStreaming(){if(stream)return;stream=new EventSource(document.body.dataset.base+'/tts/status/stream');stream.onmessage=event=>{const value=JSON.parse(event.data),mouth=document.querySelector('.enable-mouth'),talking=document.querySelector('.animation-talking');if(!mouth||!talking)return;const talkingNow=value.status==='playing';mouth.style.opacity=talkingNow?'1':'0';talking.style.animationPlayState=talkingNow?'running':'paused';};}
if(document.readyState==='loading')window.addEventListener('DOMContentLoaded',startStreaming);else startStreaming();
