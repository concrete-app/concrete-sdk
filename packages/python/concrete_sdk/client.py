import os
import requests
from typing import Optional
from langgraph_sdk import get_sync_client

from .files import FilesClient
from .vectors import VectorsClient

class ConcreteClient:
    def __init__(
        self, 
        api_key: Optional[str] = None, 
        base_url: Optional[str] = None, 
        langgraph_url: Optional[str] = None
    ):
        self.api_key = api_key or os.getenv("CONCRETE_API_KEY")
        self.base_url = (base_url or os.getenv("CONCRETE_BASE_URL", "https://europe-west6-planerhub-d731e.cloudfunctions.net")).rstrip("/")

        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({"Authorization": f"Bearer {self.api_key}"})

        # Initialize sub-clients
        self.files = FilesClient(self.base_url, self.session)
        self.vectors = VectorsClient(self.base_url, self.session)

        # Initialize LangGraph SDK wrapping the proxy
        lg_url = langgraph_url or self.base_url
        
        # Inject standard auth + the custom x-site-key expected by your langgraphProxy.js
        lg_headers = {}
        if self.api_key:
            lg_headers["Authorization"] = f"Bearer {self.api_key}"
            lg_headers["x-site-key"] = self.api_key

        self.graph = get_sync_client(url=lg_url, headers=lg_headers)
