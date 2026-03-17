import requests
from typing import List, Optional

class VectorsClient:
    def __init__(self, base_url: str, session: requests.Session):
        self.base_url = base_url
        self.session = session

    def start_vector_update(self, file_ids: Optional[List[str]] = None) -> dict:
        url = f"{self.base_url}/vectors/update"
        payload = {}
        if file_ids is not None:
            payload['file_ids'] = file_ids

        response = self.session.post(url, json=payload)
        response.raise_for_status()
        return response.json()
