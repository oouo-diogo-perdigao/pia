"""Generation epochs prevent old streaming replies from resuming after barge-in."""
import threading
import time
_lock=threading.Lock()
_epoch=0
_reference=None

def begin_playback(samples,rate):
    global _reference
    import numpy as np
    if not isinstance(getattr(samples,'ndim',None),int):return
    mono=np.mean(samples,axis=1) if samples.ndim>1 else samples
    positions=(np.arange(int(len(mono)*2000/rate))*rate/2000).astype(int)
    _reference=(mono[positions].copy(),time.monotonic())

def end_playback():
    global _reference
    _reference=None

def is_echo(samples,rate,now=None):
    """Conservative correlation guard, not a replacement for hardware AEC."""
    reference=_reference
    if reference is None:return False
    import numpy as np
    mono=np.mean(samples,axis=1) if samples.ndim>1 else samples
    positions=(np.arange(int(len(mono)*2000/rate))*rate/2000).astype(int)
    mic=mono[positions];mic=mic-np.mean(mic)
    energy=float(np.dot(mic,mic))
    if len(mic)<40 or energy<1e-9:return False
    audio,started=reference
    at=int(((time.monotonic() if now is None else now)-started)*2000)
    window=audio[max(0,at-len(mic)-800):max(0,min(len(audio),at+100))]
    if len(window)<len(mic):return False
    window=window-np.mean(window)
    correlations=np.correlate(window,mic,'valid')
    powers=np.convolve(window*window,np.ones(len(mic)),'valid')
    return bool(np.max(np.abs(correlations)/np.sqrt(np.maximum(powers*energy,1e-12)))>.85)

def epoch():
    with _lock:return _epoch

class EpochCancellation:
    def __init__(self,generation):self.generation=generation
    def is_set(self):return epoch()!=self.generation

def interrupt():
    global _epoch
    with _lock:_epoch+=1
    from .HTTPServer import TTS_MANAGER
    TTS_MANAGER.stop_tts_queue()
    TTS_MANAGER.stop()

class SpeechOnset:
    def __init__(self,seconds=.16):self.seconds=seconds;self.active=0;self.fired=False
    def feed(self,speech,seconds):
        if not speech:self.active=0;self.fired=False;return False
        self.active+=seconds
        if not self.fired and self.active>=self.seconds:self.fired=True;return True
        return False
