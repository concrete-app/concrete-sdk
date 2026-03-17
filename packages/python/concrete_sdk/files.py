import os
import requests
from typing import Optional

class FilesClient:
    def __init__(self, base_url: str, session: requests.Session):
        self.base_url = base_url
        self.session = session

    def upload_file(self, filepath: str, filename: Optional[str] = None, metadata: Optional[str] = None) -> dict:
        url = f"{self.base_url}/upload"
        
        if not filename:
            filename = os.path.basename(filepath)

        data = {}
        if metadata:
            data['metadata'] = metadata

        with open(filepath, 'rb') as f:
            files = {'file': (filename, f)}
            response = self.session.post(url, files=files, data=data)
            
        response.raise_for_status()
        return response.json()
