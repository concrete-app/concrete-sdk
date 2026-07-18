# Concrete SDK

```bash
pip install concrete-sdk
```


Werkvertrag transkribieren

```python
from langchain_google_genai import ChatGoogleGenerativeAI
from concrete_sdk.werkvertrag.transcribe import PDFTranscriber


llm = ChatGoogleGenerativeAI(
    model="gemini-3.5-flash",
    max_output_tokens=65536,
    max_retries=3,
    vertexai=True,
    project="sample",
    location="eu",
    thinking_budget=0,
)

t = PDFTranscriber(pdf_path="example.pdf", llm=llm)

await t.transcribe()

t.export_to_markdown(output_path=f"example.md")

```

Werkvertrag parsen (mit Seiten-Tracking pro Position)

```python
from concrete_sdk.werkvertrag.parser import WerkvertragParser, join_pages

tagged_text = join_pages(t.page_transcriptions)  # statt "\n".join(...) -- fuellt Position.pages
parser = WerkvertragParser(tagged_text)
vertrag = parser.parse()
vertrag.to_json(f"../data/export/werkvertrag/{file_name}.json")
```

Grobkategorie klassifizieren (deterministisch, kein LLM)

```python
from concrete_sdk.werkvertrag.grobkategorie import classify_positions

leaves = [p for p in vertrag.positionen if p.level == "leaf"]
classify_positions(leaves)  # setzt position.grobkategorie in-place
```