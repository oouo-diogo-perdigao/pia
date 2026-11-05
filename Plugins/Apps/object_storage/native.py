"""Open and drag files already downloaded by an explicitly requested app job."""
from PyQt6.QtCore import QMimeData,QUrl,Qt
from PyQt6.QtGui import QDesktopServices,QDrag
from PyQt6.QtWidgets import QApplication
from Plugins.Apps.object_storage.local_files import resolve

class NativeApp:
    def __init__(self,ui,service):self.ui=ui
    def handle(self,action,data):
        if action not in ('open-local','drag-local'):raise ValueError('Operação local desconhecida.')
        file=resolve(data['token'])
        if action=='open-local':
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(file))):raise ValueError('Não foi possível abrir o arquivo.')
        else:
            if not QApplication.mouseButtons() & Qt.MouseButton.LeftButton:
                raise ValueError('Mantenha o botão esquerdo pressionado no ícone de arraste do arquivo preparado.')
            mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(file))])
            drag=QDrag(self.ui.window);drag.setMimeData(mime)
            try:drag.exec(Qt.DropAction.CopyAction)
            finally:drag.deleteLater()
        return {'ok':True}
