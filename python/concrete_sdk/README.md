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

Werkvertrag parsen

```python

md_text = Path(f"../data/processed/werkvertrag/{file_name}.md").read_text(encoding="utf-8")
parser = WerkvertragParser(md_text)
vertrag = parser.parse()
vertrag.to_json(f"../data/export/werkvertrag/{file_name}.json")
```