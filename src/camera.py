"""One-shot camera capture. No background capture and no persistent file by default."""
import threading
_lock=threading.Lock()

def capture(device=0,width=1280,height=720):
    for name,value,minimum,maximum in (('device',device,0,16),('width',width,160,3840),('height',height,120,2160)):
        if isinstance(value,bool) or not isinstance(value,int) or not minimum<=value<=maximum:raise ValueError(f'{name} inválido.')
    try:import cv2
    except ImportError:raise RuntimeError('Instale opencv-python-headless no ambiente da PIA para usar a câmera.') from None
    if not _lock.acquire(blocking=False):raise RuntimeError('A câmera está em uso por outra captura.')
    camera=None
    try:
        camera=cv2.VideoCapture(device)
        if not camera.isOpened():raise RuntimeError('Câmera indisponível. Verifique o dispositivo e as permissões do sistema.')
        camera.set(cv2.CAP_PROP_FRAME_WIDTH,width);camera.set(cv2.CAP_PROP_FRAME_HEIGHT,height)
        frame=None
        for _ in range(4):
            ok,frame=camera.read()
            if not ok:raise RuntimeError('Não foi possível ler uma imagem da câmera.')
        ok,encoded=cv2.imencode('.png',frame)
        if not ok:raise RuntimeError('Não foi possível codificar a foto.')
        return encoded.tobytes()
    finally:
        if camera is not None:camera.release()
        _lock.release()
