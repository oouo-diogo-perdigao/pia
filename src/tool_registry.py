"""One tool catalogue for the workspace, skills, MCP and agent transports."""
import base64
import json

def spec(name,description,properties,required=()):
    return dict(name=name,description=description,inputSchema=dict(type='object',properties=properties,required=list(required),additionalProperties=False))

TOOLS=[
    spec('pia_accounts','Listar contas dos conectores, sem credenciais.',{}),
    spec('pia_resources','Consultar recursos de uma conta explicitamente escolhida.',{'plugin':{'type':'string','enum':['google','microsoft']},'account':{'type':'string'},'operation':{'type':'string','enum':['mail.list','calendar.list','files.list','drive.folders']},'params':{'type':'object'}},('plugin','account','operation')),
    spec('pia_camera','Tirar uma foto da câmera somente quando solicitado.',{'device':{'type':'integer','minimum':0,'maximum':16}}),
    spec('pia_image','Gerar imagem com a PIA.',{'prompt':{'type':'string'}},('prompt',)),
    spec('pia_music','Gerar uma música com descrição e letra opcional.',{'prompt':{'type':'string'},'lyrics':{'type':'string'},'provider':{'type':'string','enum':['local','gemini']},'duration':{'type':'integer','minimum':10,'maximum':180}},('prompt',)),
    spec('pia_delegate','Perguntar ao CLI Codex ou Gemini, usando seu login existente.',{'provider':{'type':'string','enum':['codex','gemini']},'prompt':{'type':'string'}},('provider','prompt')),
]

def call(name,arguments,resources=None):
    from jsonschema import validate
    entry=next((t for t in TOOLS if t['name']==name),None)
    if not entry:raise ValueError('Ferramenta desconhecida.')
    validate(arguments,entry['inputSchema'])
    if name in ('pia_accounts','pia_resources'):
        from .resource_plugins import get_resources
        resources=resources or get_resources()
        if name=='pia_accounts':return resources.accounts()
        return resources.call(arguments['plugin'],arguments['operation'],account=arguments['account'],**arguments.get('params',{}))
    if name=='pia_camera':
        from .camera import capture
        return {'mimeType':'image/png','data':base64.b64encode(capture(arguments.get('device',0))).decode()}
    if name=='pia_image':
        from .chat_tools import ChatTools
        return {'markdown':ChatTools().generate_image(arguments['prompt'])}
    if name=='pia_music':
        from Plugins.Apps.music.service import generate
        return generate(**arguments)
    if name=='pia_delegate':
        from Plugins.Connectors.agents.service import ask
        return ask(**arguments)

def complete_with_tools(agent,messages,model=None,allowed=None,on_delta=None):
    """Bounded real function calling. Model-supplied names cannot bypass allowlists."""
    selected=[t for t in TOOLS if t['name'] in (allowed or ())]
    history=list(messages)
    for _ in range(6):
        response=agent.complete(history,model=model,tools=[{'type':'function','function':{'name':t['name'],'description':t['description'],'parameters':t['inputSchema']}} for t in selected])
        message=response.choices[0].message
        calls=getattr(message,'tool_calls',None)
        if not calls:
            text=message.content or ''
            if on_delta:on_delta(text)
            return text
        history.append(message.model_dump(exclude_none=True))
        for tool in calls:
            if tool.function.name not in {t['name'] for t in selected}:raise ValueError('Ferramenta não autorizada nesta conversa.')
            try:result=call(tool.function.name,json.loads(tool.function.arguments))
            except Exception as exc:result={'error':str(exc)}
            # Images/audio are rendered directly; never feed base64 to an LLM.
            if isinstance(result,dict) and ('markdown' in result or 'audio_url' in result or result.get('mimeType')=='image/png'):
                if result.get('mimeType')=='image/png':
                    from .chat_tools import save_camera
                    text=save_camera(result)
                else:text=result.get('markdown') or f"[Música gerada]({result['audio_url']})"
                if on_delta:on_delta(text)
                return text
            history.append({'role':'tool','tool_call_id':tool.id,'content':json.dumps(result,ensure_ascii=False,default=str)[:32000]})
    raise RuntimeError('Limite de seis etapas de ferramentas atingido.')
