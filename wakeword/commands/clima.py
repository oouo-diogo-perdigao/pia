from __future__ import annotations

import os
from datetime import date, timedelta
import requests
from lib.utils import speak_tts

# Variáveis exigidas pelo seu sistema principal
COMMAND_NAME = "previsao do tempo"
TTS_SERVER_URL = os.getenv("TTS_SERVER_URL", "http://127.0.0.1:8765")

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Configuração padrão de localização (Altere conforme sua cidade)
DEFAULT_LOCATION = "Belo Horizonte"


def _resolve_date(when: str) -> date:
    normalized = when.strip().lower()
    today = date.today()

    if normalized in {"hoje", "today", ""}:
        return today
    if normalized in {"amanhã", "amanha", "tomorrow"}:
        return today + timedelta(days=1)

    try:
        return date.fromisoformat(when)
    except ValueError as exc:
        raise ValueError("Data inválida. Use hoje, amanhã ou YYYY-MM-DD.") from exc


def get_weather(location: str = DEFAULT_LOCATION, when: str = "hoje") -> dict:
    target_date = _resolve_date(when)

    geo_response = requests.get(
        GEOCODING_URL,
        params={
            "name": location,
            "count": 1,
            "language": "pt",
            "format": "json",
        },
        timeout=10,
    )
    geo_response.raise_for_status()
    geo_payload = geo_response.json()
    results = geo_payload.get("results") or []

    if not results:
        raise RuntimeError(f"Local não encontrado: {location}")

    place = results[0]

    forecast_response = requests.get(
        FORECAST_URL,
        params={
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "daily": (
                "temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max,weather_code"
            ),
            "timezone": "auto",
            "start_date": target_date.isoformat(),
            "end_date": target_date.isoformat(),
        },
        timeout=10,
    )
    forecast_response.raise_for_status()
    payload = forecast_response.json()
    daily = payload.get("daily") or {}

    if not daily.get("time"):
        raise RuntimeError("A API meteorológica não retornou previsão para a data.")

    return {
        "location": place.get("name", location),
        "temperature_min_c": int(round(daily["temperature_2m_min"][0])),
        "temperature_max_c": int(round(daily["temperature_2m_max"][0])),
        "precipitation_probability_max": daily["precipitation_probability_max"][0],
    }


def execute(location: str = DEFAULT_LOCATION, when: str = "hoje"):
    """Função invocada pelo carregador dinâmico de comandos."""
    try:
        data = get_weather(location, when)

        mensagem = (
            f"A previsão do tempo para {data['location']} é de "
            f"mínima de {data['temperature_min_c']} graus e máxima de {data['temperature_max_c']} graus. "
            f"A chance de chuva é de {data['precipitation_probability_max']} por cento."
        )

        print(f"[CLIMA]: {mensagem}")
        speak_tts(mensagem)

    except Exception as e:
        erro_msg = f"Não foi possível obter a previsão do tempo. Erro: {e}"
        print(f"[CLIMA ERRO]: {erro_msg}")
        speak_tts("Desculpe, não consegui obter a previsão do tempo no momento.")


# python comandos/clima.py
if __name__ == "__main__":
    print("\n--- TESTANDO EXECUÇÃO DIRETA DO COMANDO ---")
    # Testa a função execute() diretamente
    execute("Belo Horizonte", "hoje")

    # Se quiser testar outro local ou data:
    # execute("Rio de Janeiro", "amanhã")
