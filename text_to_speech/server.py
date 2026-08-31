import threading

from pathlib import Path
from src.http_server import run_http_server

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Exemplo: ~1000 linhas por arquivo (1000 linhas * 100 bytes = 100_000 bytes)
# backupCount=1 mantém o log atual e no máximo 1 arquivo antigo de backup.
max_bytes_1000_lines = 100_000


def main():
    # http_thread = threading.Thread(target=run_http_server, daemon=True)
    # http_thread.start()

    run_http_server()


if __name__ == "__main__":
    main()
