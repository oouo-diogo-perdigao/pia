"""Skill interativa demonstrando as APIs fornecidas pelo host PIA."""
from pathlib import Path


def execute(piaClose, piaSTT, piaTTS, piaInterface, piaView, piaCancelled):
    piaInterface('blink')
    piaTTS('Skill de exemplo ativada. Diga imagem, piscar, olhar ou finalizar.')
    def listen(text):
        if piaCancelled.is_set():
            return
        command = text.lower().strip(' .!?')
        if command == 'imagem':
            piaView(Path(__file__).with_name('example.png'))
        elif command == 'piscar':
            piaInterface('blink')
        elif command == 'olhar':
            piaInterface('look', True)
        elif command == 'fechar':
            piaClose()
        else:
            piaTTS('Diga imagem, piscar, olhar ou finalizar.')
    piaSTT(listen)
