"""Run the production React bundle in offscreen Chromium with local fixtures only."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['QTWEBENGINE_CHROMIUM_FLAGS']='--no-sandbox --disable-gpu'
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import Mock,patch
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from src.desktop_ui import WebShell
from src.pia import http
from src.pia.service import WorkspaceService,Apps,Job
from src.workspace_store import WorkspaceStore
from Plugins.Bot.secretaria import Secretary
from Plugins.Apps.podcast_automation.pipeline import initial

app=QApplication(['pia-react-smoke']);app.setQuitOnLastWindowClosed(False)
errors=[]
def wait(predicate,timeout=15000):
    for _ in range(timeout//25):
        QTest.qWait(25)
        if predicate():return
    raise AssertionError('React UI timeout. Console: '+str(errors[-6:]))
def js(shell,script):
    output=[];shell.view.page().runJavaScript(script,lambda result:output.append(result));wait(lambda:bool(output));return output[0]

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);store=WorkspaceStore(root/'workspace.db');chat=store.new_chat('Fixture chat')
    resources=Mock();resources.accounts.return_value=[];resources.manifests.return_value=[dict(id="google",name="Google",setup_url="https://example.invalid")];resources.config.return_value={"client_id":"fixture-client"};resources.vault.get.return_value=""
    secretary=Secretary(resources,store,Mock(),config_path=root/'secretary.json')
    def reply(chat,text,on_delta):
        answer='# Resposta\n\n**React funciona.**'
        on_delta(answer);store.append(chat,'assistant',answer);return answer
    backend=SimpleNamespace(store=store,reply=reply,speak=Mock(),resources=resources,secretary=secretary)
    calls=[]
    config={'nomes_reais':{},'campaign_details':{},'publication':{},'audio':{},'processing':{},'integrations':{},'outputs':{}}
    class FakeApps(Apps):
        def call(self,identity,action,payload,context):
            calls.append((identity,action))
            if identity=='podcast_automation':
                if action=='config':return config
                if action=='save-options':
                    config.update(outputs=payload["outputs"],integrations=payload["integrations"]);return {"ok":True}
                if action=='status':
                    latest=getattr(self,'latest',None)
                    return {'job':latest.id if latest else None,'running':bool(latest),'lines':['fixture log'],'result':None,'cursor':len(latest.events) if latest else 0}
                if action=='pipeline':return getattr(self,'snapshot',initial())
                if action=='start':
                    job=Job();context.jobs[job.id]=job;self.latest=job
                    self.snapshot={**initial(),'session':'Fixture session','progress':{'label':'Transcrever','percent':42,'processed':123,'duration':333,'speed':50,'total':7,'completed':2}}
                    job.emit('pipeline',value={**initial(),'session':'Fixture session','progress':{'label':'Transcrever','percent':42,'processed':123,'duration':333,'speed':50,'total':7,'completed':2}})
                    return {'job':job.id}
                return {'ok':True}
            if identity=='object_storage':
                if action=='accounts':return {'accounts':[{'id':'work-storage','name':'Work storage'}],'default':'work-storage'}
                if action=='buckets':return {'buckets':['podcasts','archive']}
            if identity=='screenshots':
                if action=='image':return {'id':'fixture','data':png_data(capture_image),'title':'Fixture','comment':'','mode':'selection','config':{'format':'png','border':False}}
                if action=='list-saved':return {'captures':[],'total':0,'folder':'fixture/captures'}
                if action=='config':return {'format':'png','output_folder':'','auto_save':True,'auto_copy':True}
            return {}
    from PyQt6.QtGui import QImage,QColor
    from Plugins.Apps.screenshots.native import png_data
    capture_image=QImage(32,32,QImage.Format.Format_ARGB32);capture_image.fill(QColor('#7755cc'))
    service=WorkspaceService(backend=backend,apps=FakeApps())
    def native(action,payload):
        if action=='dictate':
            job=Job();service.jobs[job.id]=job;job.emit('delta',text='texto ditado');job.emit('done');return {'job':job.id}
        raise ValueError('Native fixture action not allowed')
    service.native_handler=native
    original_dispatch=service.dispatch
    def dispatch(method,path,data,query):
        if path=='/integrations/google/accounts':return {'accounts':[{'id':'work','label':'Work','email':'fixture@example.invalid'}],'folder':''}
        if path=='/integrations/google/folders':return {'files':[{'id':'recordings','name':'Gravações'}] if data.get('folder')=='root' else [],'nextPageToken':None}
        if path=='/integrations/discord/channels':return {'channels':[]}
        return original_dispatch(method,path,data,query)
    service.dispatch=dispatch
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):http.route(self)
        def do_POST(self):http.route(self)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    origin='http://127.0.0.1:'+str(server.server_port)
    with patch.object(http,'get_service',return_value=service):
        shell=WebShell(origin+'/',origin);shell.show()
        shell.view.page().javaScriptConsoleMessage=lambda level,message,line,source:errors.append(message)
        wait(lambda:js(shell,"!!document.querySelector('.activity-rail')"))
        js(shell,"document.querySelector('.chat-name').click()")
        wait(lambda:js(shell,"document.querySelector('.view-title')?.textContent==='Fixture chat'"))
        before=len(store.chat_records())
        js(shell,"document.querySelector('[aria-label=\"Ditar no campo de mensagem\"]').click()")
        wait(lambda:js(shell,"document.querySelector('#prompt').value==='texto ditado'"))
        assert len(store.chat_records())==before and not store.messages(chat)
        js(shell,"const input=document.querySelector('#prompt');Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(input,'Olá PIA');input.dispatchEvent(new Event('input',{bubbles:true}));")
        wait(lambda:js(shell,"!document.querySelector('[aria-label=\"Enviar mensagem\"]').disabled"))
        js(shell,"document.querySelector('[aria-label=\"Enviar mensagem\"]').click()")
        wait(lambda:js(shell,"!!document.querySelector('.message.assistant h1')"))
        assert js(shell,"document.querySelector('#prompt').value==='' && document.querySelector('.message.assistant strong').textContent==='React funciona.'")
        js(shell,"document.querySelector('.app-activities [aria-label=\"Podcast Automation\"]').click()")
        wait(lambda:js(shell,"!!document.querySelector('#process')"))
        # Shutdown and continuous monitoring are mutually exclusive run options.
        shutdown_toggle="document.querySelector('#shutdown-after-processing')"
        monitor_toggle="document.querySelector('#monitor-sessions')"
        js(shell,shutdown_toggle+'.click()')
        wait(lambda:js(shell,shutdown_toggle+'.checked && !'+monitor_toggle+'.checked'))
        js(shell,monitor_toggle+'.click()')
        wait(lambda:js(shell,monitor_toggle+'.checked && !'+shutdown_toggle+'.checked'))
        js(shell,shutdown_toggle+'.click()')
        wait(lambda:js(shell,shutdown_toggle+'.checked && !'+monitor_toggle+'.checked'))
        js(shell,shutdown_toggle+'.click()')
        wait(lambda:js(shell,'!'+shutdown_toggle+'.checked && !'+monitor_toggle+'.checked'))
        # Saving is disabled until a field changes; choose a real folder ID via the tree.
        assert js(shell,"[...document.querySelectorAll('button')].find(b=>b.textContent==='Salvar opções').disabled")
        js(shell,"[...document.querySelectorAll('button')].find(b=>b.textContent.includes('Pasta de gravações:')).click()")
        wait(lambda:js(shell,"!!document.querySelector('[aria-label=\"Expandir Meu Drive\"]')"))
        js(shell,"document.querySelector('[aria-label=\"Expandir Meu Drive\"]').click()")
        wait(lambda:js(shell,"[...document.querySelectorAll('button')].some(b=>b.textContent==='Gravações')"))
        js(shell,"[...document.querySelectorAll('button')].find(b=>b.textContent==='Gravações').click()")
        wait(lambda:js(shell,"![...document.querySelectorAll('button')].find(b=>b.textContent==='Usar esta pasta').disabled"))
        js(shell,"[...document.querySelectorAll('button')].find(b=>b.textContent==='Usar esta pasta').click()")
        wait(lambda:js(shell,"![...document.querySelectorAll('button')].find(b=>b.textContent==='Salvar opções').disabled"))
        js(shell,"[...document.querySelectorAll('button')].find(b=>b.textContent==='Salvar opções').click()")
        wait(lambda:config.get('integrations',{}).get('google_folder')=='recordings')
        wait(lambda:js(shell,"[...document.querySelectorAll('button')].find(b=>b.textContent==='Salvar opções').disabled"))
        assert config['integrations']['google_account']=='work'
        wait(lambda:js(shell,"!!document.querySelector('.success-toast')"))
        js(shell,"window.dispatchEvent(new Event('pia:toast-history'))")
        wait(lambda:js(shell,"document.body.textContent.includes('Histórico de notificações')"))
        js(shell,"document.querySelector('.mantine-Modal-close').click()")
        js(shell,"[...document.querySelectorAll('button')].find(b=>b.textContent.includes('Bucket de destino:')).click()")
        wait(lambda:js(shell,"[...document.querySelectorAll('button')].some(b=>b.textContent==='podcasts')"))
        js(shell,"[...document.querySelectorAll('button')].find(b=>b.textContent==='podcasts').click()")
        wait(lambda:js(shell,"![...document.querySelectorAll('button')].find(b=>b.textContent==='Usar este bucket').disabled"))
        js(shell,"[...document.querySelectorAll('button')].find(b=>b.textContent==='Usar este bucket').click()")
        wait(lambda:js(shell,"![...document.querySelectorAll('button')].find(b=>b.textContent==='Salvar opções').disabled"))
        js(shell,"[...document.querySelectorAll('button')].find(b=>b.textContent==='Salvar opções').click()")
        wait(lambda:config.get('integrations',{}).get('storage_bucket')=='podcasts')
        assert config['integrations']['storage_account']=='work-storage'
        js(shell,"[...document.querySelectorAll('button')].find(button=>button.textContent==='Campanhas').click()")
        wait(lambda:js(shell,"!!document.querySelector('#save-config')"))
        assert js(shell,"document.querySelector('#save-config').disabled")
        js(shell,"history.back()")
        wait(lambda:js(shell,"!!document.querySelector('#process')"))
        assert ('podcast_automation','start') not in calls
        js(shell,"document.querySelector('#process').click()")
        wait(lambda:('podcast_automation','start') in calls)
        wait(lambda:js(shell,"document.querySelector('.work-progress')?.textContent.includes('42.0%')"))
        assert js(shell,"document.querySelector('.work-progress').textContent.includes('00:02:03 / 00:05:33') && document.querySelector('.work-progress').textContent.includes('Speed 50.0') && document.querySelector('.work-progress').textContent.includes('2/7')")
        js(shell,"history.back()")
        wait(lambda:js(shell,"document.querySelector('.view-title')?.textContent==='Fixture chat'"))
        js(shell,"history.forward()")
        wait(lambda:js(shell,"!!document.querySelector('#process')"))
        assert calls.count(('podcast_automation','start'))==1
        # Reorder by dragging, persist order, without navigating or dispatching actions.
        js(shell,"(()=>{const drag=new DataTransfer();drag.setData('application/x-pia-app','screenshots');const target=document.querySelector('[aria-label=\"Podcast Automation\"]').parentElement;target.dispatchEvent(new DragEvent('drop',{dataTransfer:drag,bubbles:true,cancelable:true}));})()")
        wait(lambda:bool(store.get('ui:app-order',[])) and store.get('ui:app-order',[]).index('screenshots')<store.get('ui:app-order',[]).index('podcast_automation'))
        assert calls.count(('podcast_automation','start'))==1
        # Follow-tail stops after manual scroll and resumes at the bottom.
        log_lines='\n'.join('line '+str(index) for index in range(150))
        job=service.apps.latest
        job.emit('log',text=log_lines)
        wait(lambda:js(shell,"document.querySelector('.log-viewer')?.textContent.includes('line 149')"))
        js(shell,"var log=document.querySelector('.log-viewer');log.scrollTop=0;log.dispatchEvent(new Event('scroll',{bubbles:true}));")
        job.emit('log',text='after manual scroll')
        wait(lambda:js(shell,"document.querySelector('.log-viewer').textContent.includes('after manual scroll')"))
        assert js(shell,"document.querySelector('.log-viewer').scrollTop===0")
        js(shell,"var log=document.querySelector('.log-viewer');log.scrollTop=log.scrollHeight;log.dispatchEvent(new Event('scroll',{bubbles:true}));")
        job.emit('log',text='following again')
        wait(lambda:js(shell,"document.querySelector('.log-viewer').textContent.includes('following again')"))
        assert js(shell,"(()=>{var log=document.querySelector('.log-viewer');return log.scrollHeight-log.scrollTop-log.clientHeight<25;})()")
        preview=Path(__file__).resolve().parents[1]/'cache/main/desktop/previews';preview.mkdir(parents=True,exist_ok=True)
        QTest.qWait(300);shell.view.grab().save(str(preview/'react-podcast.png'))
        # Secretary saves enable on change, disable on revert and reset after persistence.
        js(shell,"document.querySelector('[aria-label=\"Bots\"]').click()")
        wait(lambda:js(shell,"[...document.querySelectorAll('button')].some(b=>b.textContent==='Salvar preferências')"))
        assert js(shell,"[...document.querySelectorAll('button')].find(b=>b.textContent==='Salvar preferências').disabled")
        toggle="[...document.querySelectorAll('label')].find(label=>label.textContent==='Ativar secretária').control.click()"
        js(shell,toggle)
        wait(lambda:js(shell,"![...document.querySelectorAll('button')].find(b=>b.textContent==='Salvar preferências').disabled"))
        js(shell,toggle)
        wait(lambda:js(shell,"[...document.querySelectorAll('button')].find(b=>b.textContent==='Salvar preferências').disabled"))
        js(shell,toggle)
        wait(lambda:js(shell,"![...document.querySelectorAll('button')].find(b=>b.textContent==='Salvar preferências').disabled"))
        js(shell,"[...document.querySelectorAll('button')].find(b=>b.textContent==='Salvar preferências').click()")
        wait(lambda:js(shell,"[...document.querySelectorAll('button')].find(b=>b.textContent==='Salvar preferências').disabled"))
        js(shell,"document.querySelector('[aria-label=\"Conectores\"]').click()")
        wait(lambda:js(shell,"document.querySelector('.view-title')?.textContent==='Conectores / Google'"))
        wait(lambda:js(shell,"[...document.querySelectorAll('label')].some(label=>label.textContent==='Client ID')"))
        # Environment settings use an isolated fixture and do not expose live secrets.
        service.settings=lambda:[dict(id='general',name='PIA · Geral',fields=[dict(name='COUNT__INT',base='COUNT',type='int',value='1',sensitive=False,link='https://example.invalid')])]
        js(shell,"document.querySelector('.rail-bottom [aria-label=\"Configurações\"]')?.click() || document.querySelector('[aria-label=\"Configurações\"]').click()")
        wait(lambda:js(shell,"[...document.querySelectorAll('button')].some(b=>b.textContent==='Salvar variáveis')"))
        assert js(shell,"[...document.querySelectorAll('button')].find(b=>b.textContent==='Salvar variáveis').disabled")
        js(shell,"var field=[...document.querySelectorAll('label')].find(l=>l.textContent==='COUNT__INT').control;Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(field,'2');field.dispatchEvent(new Event('input',{bubbles:true}));")
        wait(lambda:js(shell,"![...document.querySelectorAll('button')].find(b=>b.textContent==='Salvar variáveis').disabled"))
        js(shell,"var field=[...document.querySelectorAll('label')].find(l=>l.textContent==='COUNT__INT').control;Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(field,'1');field.dispatchEvent(new Event('input',{bubbles:true}));")
        wait(lambda:js(shell,"[...document.querySelectorAll('button')].find(b=>b.textContent==='Salvar variáveis').disabled"))
        editor=WebShell(origin+'/apps/screenshots/capture.html?id=fixture',origin);editor.show()
        wait(lambda:js(editor,"!!window.piaCapture?.ready"))
        assert js(editor,"document.querySelector('#free').classList.contains('mantine-Button-root') && document.querySelector('#canvas').width>1")
        js(editor,"window.piaCapture.fullScreen()")
        wait(lambda:('screenshots','finalize') in calls)
        editor.hide()
        shell.hide();shell.view.setUrl(__import__('PyQt6.QtCore',fromlist=['QUrl']).QUrl('about:blank'))
        server.shutdown();server.server_close()
        assert not [error for error in errors if 'Uncaught' in error],errors
print('React/Mantine: chat Markdown, native history, app order, podcast action safety, progress and log follow-tail: OK')

# A synthetic saved capture discards its private raw PNG and never touches the real clipboard.
from Plugins.Apps.screenshots.native import NativeApp,png_data
from PyQt6.QtGui import QImage,QColor
with tempfile.TemporaryDirectory() as directory:
    root=Path(directory)
    ui=SimpleNamespace(overlay=SimpleNamespace(user_hidden=True,capture_hidden=False),main_action=Mock())
    ui.main_action.isChecked.return_value=False
    prefs={'format':'png','quality':92,'output_folder':str(root/'saved'),'auto_save':True,'auto_copy':True}
    with patch('src.config_paths.BASE_DIR',root),patch('Plugins.Apps.screenshots.native.config',return_value=prefs),patch('Plugins.Apps.screenshots.native.QApplication.clipboard',return_value=Mock()) as clipboard:
        native=NativeApp(ui,None)
        image=QImage(32,32,QImage.Format.Format_ARGB32);image.fill(QColor('#7755cc'))
        identity=native.store_capture(image)
        raw=native.records[identity]['path'];assert raw.parent==root/'logs/screenshots'
        result=native.handle('finalize',{'data':png_data(image),'title':'Fixture'})
        assert (root/'saved'/result['name']).is_file()
        assert not raw.exists() and not native.records
        clipboard.return_value.setImage.assert_called_once()
print('Screenshot raw cleanup in logs/screenshots after successful save: OK')
