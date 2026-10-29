from podcast_automation import settings

from podcast_automation.objectStorageManager import ObjectStorageManager
from podcast_automation.rssTranscriptionUpdate import RssTranscriptionUpdater


def main() -> None:

    print("========================================")
    print(" Reconstrução de RSS e transcrições")
    print("========================================")

    obj_storage = ObjectStorageManager()
    rss_updater = RssTranscriptionUpdater(obj_storage)

    resultado = rss_updater.updateRssTranscriptionFiles()

    print("\n========================================")
    print(" Resultado")
    print("========================================")
    print(f"Campanhas processadas: {resultado['foldersProcessed']}")

    if resultado["errors"]:
        print(f"Erros: {len(resultado['errors'])}")

        for erro in resultado["errors"]:
            print(f" - {erro['folder']}: {erro['erro']}")
        raise RuntimeError('Reconstrução de feeds falhou; consulte os erros acima.')
    else:
        print("Nenhum erro encontrado.")


if __name__ == "__main__":
    main()
