import requests
from typing import List, Optional

class VectorsClient:
    def __init__(self, base_url: str, session: requests.Session):
        self.base_url = base_url
        self.session = session

    def start_vector_update(self) -> dict:
        url = f"{self.base_url}/start_vector_update"
        response = self.session.post(url)
        response.raise_for_status()
        return response.json()
