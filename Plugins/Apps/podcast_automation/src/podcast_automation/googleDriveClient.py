"""Podcast adapter. Authentication, listing and downloads belong to the Google plugin."""
from pathlib import Path
from Plugins.Connectors.google.drive import Drive
from .settings import get_config,get_download_dir
class GoogleDriveClient:
    def __init__(self):
        self.plugin=Drive()
        self.account=self.plugin.account(get_config().get('integrations',{}).get('google_account'))
    def list_zip_files(self,folder_path):
        files=[];cursor=None
        while True:
            response=self.plugin.list(self.account,folder_path,cursor=cursor)
            files.extend(f for f in response.get('files',[]) if f['name'].lower().endswith('.zip'))
            cursor=response.get('nextPageToken')
            if not cursor:break
        return files
    def download_file(self,file):
        name=Path(file['name']).name
        if name!=file['name'] or name in ('.','..'):raise ValueError('Nome de arquivo do Drive inválido.')
        target=get_download_dir()/name
        return target if target.exists() else self.plugin.download(file['id'],target,self.account)
    def rename_processed(self,id,name,status='ok'):
        suffix='-'+status
        if name.lower().endswith(suffix+'.zip'):return
        new=name[:-4]+suffix+'.zip' if name.lower().endswith('.zip') else name+suffix
        self.plugin.rename(id,new,self.account)
