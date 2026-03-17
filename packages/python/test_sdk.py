from concrete_sdk import ConcreteClient

client = ConcreteClient(base_url="http://localhost:5001/v1", api_key="my-test-key")
print("SDK Initialized!")
print("Has files subclient?", hasattr(client, "files"))
print("Has vectors subclient?", hasattr(client, "vectors"))
print("Has graph (langgraph-sdk)?", hasattr(client, "graph"))
