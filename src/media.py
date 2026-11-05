"""Cross-window playback leases; abandoned clients expire automatically."""
import threading
import time

class MediaSessions:
    def __init__(self):self.clients={};self.lock=threading.Lock()
    def update(self,client,playing):
        if not isinstance(client,str) or not 1<=len(client)<=100 or not isinstance(playing,bool):raise ValueError('Estado de reprodução inválido.')
        with self.lock:
            now=time.monotonic()
            self.clients={key:stamp for key,stamp in self.clients.items() if now-stamp<15}
            if playing:self.clients[client]=now
            else:self.clients.pop(client,None)
            return bool(self.clients)
