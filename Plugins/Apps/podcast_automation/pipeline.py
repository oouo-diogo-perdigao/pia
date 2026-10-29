"""Persistent snapshots from structured child-process events; no progress spam in logs."""
STAGES=('Obter ZIP','Extrair e identificar','Mixar áudio','Editar e compilar','Transcrever','Gerar legendas','Gerar resumo','Preparar arquivos','Publicar','Atualizar RSS e página','Finalizar e limpar')

def initial():
    return dict(session='',stages=[{'name':n,'status':'pending'} for n in STAGES],current=None,progress=None,artifacts=[],history=[])

def apply(state,event):
    kind=event.get('kind')
    if kind=='session':
        history=state.get('history',[])
        state.clear();state.update(initial(),session=event.get('name',''),history=history)
    elif kind=='stage':
        index=int(event['index'])
        if not 0<=index<len(STAGES):return
        previous=state['current']
        if previous is not None and previous!=index:
            state['stages'][previous]['status']='done'
            for step in range(previous+1,index):state['stages'][step]['status']='skipped'
        state['current']=index;state['stages'][index]['status']='running';state['progress']=None
    elif kind=='progress':state['progress']={k:v for k,v in event.items() if k!='kind'}
    elif kind=='artifact':
        if event.get('url','').startswith(('https://','http://')):state['artifacts'].append({'name':event['name'],'url':event['url']})
    elif kind in ('complete','failed','skipped'):
        if state['current'] is not None:state['stages'][state['current']]['status']={'complete':'done','failed':'error','skipped':'skipped'}[kind]
        if kind=='skipped':
            for step in state['stages']:
                if step['status']=='pending':step['status']='skipped'
        state['error']=event.get('error','')
        if state.get('session'):
            state['history']=(state.get('history',[])+[{'session':state['session'],'status':kind,'artifacts':[dict(item) for item in state['artifacts']]}])[-50:]
