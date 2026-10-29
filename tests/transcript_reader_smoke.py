"""Exercise the actual exported HTML reader in Chromium, using synthetic sessions."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['QTWEBENGINE_CHROMIUM_FLAGS']='--no-sandbox --disable-gpu'
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Plugins/Apps/podcast_automation/src'))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtTest import QTest
from PyQt6.QtCore import QUrl
from src.desktop_ui import WebShell
from podcast_automation.transcripts_page import render

app=QApplication(['pia-reader-smoke'])
view=QWebEngineView();view.resize(1280,820)
errors=[]
view.page().javaScriptConsoleMessage=lambda level,message,line,source:errors.append(message)
def wait(predicate):
    for _ in range(300):
        QTest.qWait(25)
        if predicate():return
    raise AssertionError('Reader timeout: '+str(errors))
def js(script):
    result=[];view.page().runJavaScript(script,lambda value:result.append(value))
    wait(lambda:bool(result));return result[0]
directory=Path(__file__).resolve().parents[1]/'cache/main/desktop/previews'
directory.mkdir(parents=True,exist_ok=True)
target=directory/'transcripts-reader.html'
target.write_text(render([dict(title=f'Sessão {i}',content=f'Narrador: Texto completo da sessão {i}.\nJogador: Olá, PIA!') for i in range(1,4)],None,{'title':'Campanha de demonstração'}),encoding='utf-8')
view.load(QUrl.fromLocalFile(str(target)));view.show()
wait(lambda:js("document.querySelectorAll('.session').length===3"))
js("Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>window.copied=text}})")
js("document.querySelector('[data-copy=session-1]').click()")
wait(lambda:js("window.copied?.includes('Texto completo da sessão 1.')"))
js("var search=document.querySelector('#search');search.value='sessao 2';search.dispatchEvent(new Event('input'));document.querySelector('#select-visible').click();document.querySelector('#copy-selected').click()")
wait(lambda:js("window.copied?.includes('Texto completo da sessão 2.') && !window.copied.includes('Texto completo da sessão 1.')"))
assert js("document.querySelectorAll('.session:not([hidden])').length===1 && document.body.textContent.includes('Texto completo da sessão 3.')")
js("var search=document.querySelector('#search');search.value='';search.dispatchEvent(new Event('input'));document.querySelector('#select-visible').click();document.querySelector('#copy-selected').click()")
wait(lambda:js("window.copied?.includes('Texto completo da sessão 1.') && window.copied.includes('Texto completo da sessão 3.')"))
QTest.qWait(250);view.grab().save(str(directory/'transcripts-reader.png'))
assert not [error for error in errors if 'Uncaught' in error],errors
view.close()
print('Exported transcripts: accent-insensitive search, full embedded content, single/multiple copy and navigation: OK')
