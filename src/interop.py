"""Authenticated MCP and AG-UI adapters sharing the PIA tool registry."""
import json
import uuid
from urllib.parse import urlsplit


def run(text,chat=None,on_delta=None,context=None):
    if not isinstance(text,str) or not text.strip() or len(text)>100000:raise ValueError('Mensagem inválida.')
    from .pia.service import get_service
    service=get_service()
    if context:
        import hashlib
        key='interop:thread:'+hashlib.sha256(str(context).encode()).hexdigest()
        chat=service.store.get(key)
        if not chat or not any(item['id']==chat for item in service.store.chat_records()):
            chat=service.store.new_chat('Agente externo');service.store.set(key,chat)
    if chat is None:chat=service.store.new_chat('Agente externo')
    elif not any(item['id']==chat for item in service.store.chat_records()):raise ValueError('Conversa inexistente.')
    return service.backend.reply(chat,text,on_delta=on_delta)

def rpc(body,protocol):
    if not isinstance(body,dict) or body.get('jsonrpc')!='2.0' or not isinstance(body.get('method'),str):
        return {'jsonrpc':'2.0','id':None,'error':{'code':-32600,'message':'Requisição JSON-RPC inválida.'}}
    if protocol!='mcp':return {'jsonrpc':'2.0','id':body.get('id'),'error':{'code':-32601,'message':'Protocolo não suportado.'}}
    identity=body.get('id');method=body['method'];params=body.get('params') or {}
    def ok(result):return {'jsonrpc':'2.0','id':identity,'result':result}
    def error(code,message):return {'jsonrpc':'2.0','id':identity,'error':{'code':code,'message':message}}
    if not isinstance(params,dict):return error(-32602,'params deve ser um objeto.')
    if 'id' not in body and not method.startswith('notifications/'):return error(-32600,'Requisições devem possuir id.')
    try:
        if protocol=='mcp':
            from .tool_registry import TOOLS,call
            if method=='initialize':
                version=params.get('protocolVersion')
                if version not in ('2025-03-26','2025-06-18','2025-11-25'):version='2025-11-25'
                return ok({'protocolVersion':version,'capabilities':{'tools':{'listChanged':False}},'serverInfo':{'name':'pia','version':'1.0.0'}})
            if method.startswith('notifications/') and identity is None:return None
            if method=='ping':return ok({})
            if method=='tools/list':return ok({'tools':TOOLS})
            if method=='tools/call':
                try:
                    result=call(params['name'],params.get('arguments',{}))
                    content=[{'type':'image',**result}] if isinstance(result,dict) and result.get('mimeType')=='image/png' else [{'type':'text','text':json.dumps(result,ensure_ascii=False,default=str)}]
                    return ok({'content':content,'isError':False})
                except Exception as exc:return ok({'content':[{'type':'text','text':str(exc)}],'isError':True})
        return error(-32601,'Método não suportado por este perfil da PIA.')
    except (ValueError,KeyError,TypeError) as exc:return error(-32602,str(exc))
    except Exception:return error(-32603,'O agente não concluiu a operação. Consulte os logs da PIA.')

def route(handler):
    path=urlsplit(handler.path).path
    if path not in ('/protocols/mcp','/protocols/ag-ui','/action/camera','/v1/music/generations') and not path.startswith('/v1/music/files/'):return False
    if not handler._authorize_openai_request():return True
    if handler.headers.get('Origin'):
        port=handler.server.server_address[1]
        if handler.headers['Origin'] not in (f'http://localhost:{port}',f'http://127.0.0.1:{port}'):
            handler.send_json(403,{'error':'Origem não autorizada.'});return True
    try:
        if path.startswith('/v1/music/files/') and handler.command=='GET':
            from Plugins.Apps.music.service import audio_file
            file=audio_file(path.rsplit('/',1)[1]);handler._send(200,file.read_bytes(),'audio/mpeg' if file.suffix=='.mp3' else 'audio/wav');return True
        if handler.command!='POST':handler.send_json(405,{'error':'Use POST.'});return True
        length=int(handler.headers.get('Content-Length','0'))
        if not 0<length<=2*1024**2:raise ValueError('Corpo JSON obrigatório, limitado a 2 MiB.')
        body=json.loads(handler.rfile.read(length))
        if not isinstance(body,dict):raise ValueError('O corpo deve ser um objeto JSON.')
        if path=='/action/camera':
            from .camera import capture
            handler._send(200,capture(body.get('device',0),body.get('width',1280),body.get('height',720)),'image/png')
        elif path=='/v1/music/generations':
            from Plugins.Apps.music.service import generate
            if set(body)-{'prompt','lyrics','provider','duration'}:raise ValueError('Parâmetros musicais desconhecidos.')
            result=generate(**body);handler.send_json(200,{**result,'audio_url':'/v1/music/files/'+result['file']})
        elif path=='/protocols/mcp':
            result=rpc(body,path.rsplit('/',1)[-1])
            if result is None:handler._send(202,b'','application/json')
            else:handler.send_json(200,result)
        else:
            messages=body.get('messages',[])
            if not messages or messages[-1].get('role')!='user':raise ValueError('Envie uma mensagem user no RunAgentInput.')
            text=messages[-1].get('content','');thread=body.get('threadId');run_id=body.get('runId') or uuid.uuid4().hex
            if not isinstance(thread,str) or not thread:raise ValueError('threadId é obrigatório.')
            handler.send_response(200);handler.send_header('Content-Type','text/event-stream');handler.send_header('Cache-Control','no-cache');handler.end_headers()
            def emit(event):handler.wfile.write(('data: '+json.dumps(event,ensure_ascii=False)+'\n\n').encode());handler.wfile.flush()
            identity=uuid.uuid4().hex
            emit({'type':'RUN_STARTED','threadId':thread,'runId':run_id})
            emit({'type':'TEXT_MESSAGE_START','messageId':identity,'role':'assistant'})
            try:
                run(text,context=thread,on_delta=lambda delta:emit({'type':'TEXT_MESSAGE_CONTENT','messageId':identity,'delta':delta}))
                emit({'type':'TEXT_MESSAGE_END','messageId':identity});emit({'type':'RUN_FINISHED','threadId':thread,'runId':run_id})
            except Exception:emit({'type':'RUN_ERROR','message':'A PIA não concluiu a execução. Consulte os logs.'})
        return True
    except (ValueError,KeyError,TypeError) as exc:handler.send_json(400,{'error':str(exc)});return True
    except (BrokenPipeError,ConnectionResetError):return True
    except Exception as exc:handler.send_json(503,{'error':str(exc)});return True
