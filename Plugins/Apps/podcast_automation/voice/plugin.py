"""Comandos de voz do app Podcast Automation integrado à PIA."""

from pathlib import Path
import logging
from .controller import PodcastJob, normalize


def project_path():
    return Path(__file__).resolve().parents[1]


def execute(piaSTT, piaTTS, piaInterface, piaView, piaCancelled):
    job = PodcastJob(project_path())

    def listen(text):
        command = normalize(text)
        if command in (
            "iniciar",
            "processar",
            "iniciar processamento",
            "processar podcasts",
        ):
            try:
                job.start()
                piaInterface("processing", True)
                piaTTS(
                    "Processamento iniciado. Diga status para acompanhar, ou parar processamento para interromper."
                )
            except Exception as exc:
                logging.exception("[PODCAST SKILL] Não foi possível iniciar")
                piaTTS(str(exc))
        elif command in ("parar", "parar processamento", "parar tarefa"):
            if job.snapshot()["state"] in ("running", "stopping"):
                job.stop()
                piaTTS("Solicitei a parada. Os arquivos de trabalho serão preservados.")
            else:
                piaTTS("Não há processamento em execução.")
        elif command in ("status", "progresso", "andamento", "situacao"):
            state = job.snapshot()
            if state["state"] == "running":
                percent = (
                    f", {state['percent']} por cento"
                    if state["percent"] is not None
                    else ""
                )
                piaTTS("Agora: " + state["stage"] + percent + ".")
            else:
                names = dict(
                    idle="Aguardando início",
                    stopping="Parando",
                    stopped="Interrompido",
                    completed="Processamento concluído",
                    failed="Falha no processamento; consulte o log do podcast",
                )
                piaTTS(names[state["state"]] + ".")
        elif command in ("abrir rss", "abrir transcricoes"):
            name = "rss" if command == "abrir rss" else "transcricoes"
            url = job.snapshot()["links"].get(name)
            if url:
                piaView(url)
            else:
                piaTTS("Este link ainda não foi publicado nesta execução.")
        else:
            piaTTS(
                "Diga iniciar, status, parar processamento, abrir RSS ou abrir transcrições. Diga finalizar para sair."
            )

    piaSTT(listen)
    piaTTS(
        "Skill de podcast ativada. Diga iniciar para processar as gravações pendentes. Isso pode publicar arquivos no armazenamento configurado. Diga finalizar para sair."
    )
    previous = ("idle", None)
    try:
        while not piaCancelled.wait(0.2):
            snapshot = job.snapshot()
            state = snapshot["state"]
            key = (state, snapshot["log_path"])
            if key != previous and state in ("completed", "failed", "stopped"):
                piaInterface("processing", False)
                if state == "completed":
                    piaTTS(
                        "Processamento concluído. Você pode pedir para abrir o RSS ou as transcrições, ou dizer finalizar."
                    )
                elif state == "failed":
                    piaTTS(
                        "O processamento falhou. Consulte o log do podcast. Os arquivos de trabalho foram preservados."
                    )
                else:
                    piaTTS("Processamento interrompido.")
            previous = key
    finally:
        job.stop()
