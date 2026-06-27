# Werkvertrag, Preisanfrage & Materialofferte

Three document types, three different pipelines -- pick the one that matches your input:

| Document | Pipeline | LLM needed? |
|---|---|---|
| Werkvertrag | scanned PDF, broken text layer -> LLM transcribes to text -> deterministic parser builds the position tree -> optional LLM material classification enriches each position | yes, for transcription and (optionally) material classification |
| Preisanfrage | one fixed Abacus/Excel-export template with a real text layer -> deterministic `pdfplumber` parsing | no |
| Materialofferte | one different layout per supplier -> LLM maps the PDF directly onto a fixed schema | yes |

All LLM-using functions take the LLM as a parameter -- this package never constructs a model
itself, so any `langchain`-style chat model works (Gemini, OpenAI, etc.).

The snippets below use `asyncio.run(...)`, which is correct in a plain script but raises
`RuntimeError: asyncio.run() cannot be called from a running event loop` in a Jupyter notebook
(the kernel already has one running) -- in a notebook cell, use top-level `await ...` instead.

## Turn PDF to Werkvertrag JSON

```python
from langchain_google_genai import ChatGoogleGenerativeAI
from concrete_sdk.werkvertrag.transcribe import transcribe_pdf_to_text
from concrete_sdk.werkvertrag.parser import WerkvertragParser
import asyncio

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    max_output_tokens=65536,  # transcribe.py's chunking (15 pages/chunk) is calibrated for this ceiling
    max_retries=3,
    vertexai=True,
    project="beta-16080",
    location="europe-west4",
    thinking_budget=0,
)

pdf_path = Path(__file__).parent / "example1.pdf"
pdf_block = {"data": base64.b64encode(pdf_path.read_bytes()).decode("ascii")}

text = asyncio.run(transcribe_pdf_to_text(pdf_block, llm=llm))

wv = wv_parser = WerkvertragParser(text)
wv.export_json("example1.json")
```

## Enrich Werkvertrag positions with material classification (LLM)

The parser never fills `LvPosition.material` -- it's an LLM enrichment step that runs after the
position tree is built. `enrich_materials` walks the positions in document order and asks the
model, one position at a time, to reuse a material label already assigned earlier in the same
contract, mint a new one, or assign none -- this keeps "Gipskartonplatte" and "Gipsplatte 12.5mm
Feuerschutz" from becoming two different labels for the same material across one contract, which
parallel/batched calls couldn't guarantee.

```python
from concrete_sdk.werkvertrag.material import enrich_materials
import asyncio

asyncio.run(enrich_materials(wv, llm=llm))

print(wv.by_material("Gipsplatte"))  # list[LvPosition] -- requires enrich_materials to have run
```

## Parse a Preisanfrage (no LLM)

```python
from concrete_sdk.werkvertrag.preisanfrage import Preisanfrage

pa = Preisanfrage.from_pdf("preisanfrage.pdf")

print(pa.meta)               # PreisanfrageMeta: Kommission, Lieferant, Projektleiter, ...
print(pa.positions)          # list[PreisanfragePosition]: Bezeichnung, Stk, L/B/H mm, m1/m2/m3
print(pa.gruppen_totale)     # list[GruppenTotal] -- per-building/variant subtotals, if present
print(pa.check_plausibility())  # None if sums check out, else a warning string

pa.export_json("preisanfrage.json")
```

Only handles the one fixed Abacus export column layout (`Pos. | Bezeichnung | Stk | L mm | B mm
| H mm | m1 | m2 | m3`) -- a differently-columned export raises rather than silently mis-parsing.

## Extract a Materialofferte (LLM, any supplier layout)

```python
from langchain_google_genai import ChatGoogleGenerativeAI
from concrete_sdk.werkvertrag.materialofferte import extract_materialofferte
import asyncio

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    vertexai=True,
    project="beta-16080",
    location="europe-west4",
)

pdf_path = Path("offerte.pdf")
pdf_block = {"data": base64.b64encode(pdf_path.read_bytes()).decode("ascii")}

mo = asyncio.run(extract_materialofferte(pdf_block, llm=llm))

print(mo.meta)              # OfferteMeta: Lieferant, Offerte-Nr., Datum, Objekt, ...
print(mo.positions)         # list[OffertePosition]: Bezeichnung, Menge, Einheit, Preise
print(mo.totals)            # OfferteTotals: Brutto/Netto, Rabatt, Skonto, MWST
print(mo.check_plausibility())  # None if position totals sum to total_brutto, else a warning string

(Path("offerte.json")).write_text(mo.model_dump_json(indent=2))
```
