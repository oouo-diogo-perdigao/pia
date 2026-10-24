from .weather import get_weather


def execute(piaTTS, piaInterface):
    piaInterface('thinking', True)
    try:
        data = get_weather()
        message = (f"A previsão do tempo para {data['location']} é de "
                   f"mínima de {data['temperature_min_c']} graus e máxima de {data['temperature_max_c']} graus. "
                   f"A chance de chuva é de {data['precipitation_probability_max']} por cento.")
    except Exception:
        message = 'Não consegui obter a previsão do tempo no momento.'
    finally:
        piaInterface('thinking', False)
    # A sessão termina automaticamente quando este áudio realmente acaba de tocar.
    piaTTS(message)
