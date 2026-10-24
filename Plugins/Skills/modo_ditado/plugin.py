import unicodedata


def execute(piaSTT, piaInsert, piaKey, piaClose):
    last_text = ''
    def listen(text):
        nonlocal last_text
        command = ''.join(c for c in unicodedata.normalize('NFD', text.lower()) if not unicodedata.combining(c)).strip(' .!?')
        if command in ('encerrar modo ditado', 'desativar modo ditado'):
            piaClose()
        elif command in ('apagar', 'deletar'):
            for _ in last_text:
                piaKey('backspace')
            last_text = ''
        elif command in ('enviar', 'enter'):
            piaKey('enter')
            last_text = ''
        elif command in ('selecionar tudo', 'selecionar todo'):
            piaKey('ctrl', 'a')
        elif command == 'copiar':
            piaKey('ctrl', 'c')
        elif command == 'colar':
            piaKey('ctrl', 'v')
        elif text.strip():
            last_text = text.strip() + ' '
            piaInsert(last_text)
    # As palavras globais de encerramento são interceptadas pela PIA antes deste callback.
    piaSTT(listen)
