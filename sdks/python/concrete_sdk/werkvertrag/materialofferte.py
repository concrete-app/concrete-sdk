"""LLM-based extraction of Materialofferte (supplier quote) PDFs into a fixed schema.

Unlike Werkvertrag (one fixed template, deterministically parsed) or Preisanfrage (one fixed
Abacus export template, parsed via pdfplumber coordinates), every Materialofferte has its own
layout -- one supplier, one column/description format. A coordinates-based parser would need to
be rewritten per supplier, which doesn't scale. Instead an LLM maps the PDF directly onto a fixed
pydantic schema, which is robust to per-supplier format variance while keeping the actual
plausibility-check logic deterministic, not the model's job.

The PDF is sent directly as multimodal content rather than pre-extracted via pdfplumber/OCR: that
removes a lossy text-extraction stage entirely -- some supplier PDFs are purely scanned (no text
layer, empty extraction), and on others text-extraction corrupts "m²" into garbage like "m?" or
"mz". With direct PDF input the model sees the original character, not a broken intermediate.

Like `transcribe.py` and `material.py`, the LLM is a caller-supplied parameter -- pass any
`langchain`-style chat model (anything with `.with_structured_output(...)`); this module doesn't
construct one itself.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

# Safety net in case the model still carries over a broken square/cube sign variant (e.g. "m?",
# "mz" instead of "m2") despite the prompt rule -- observed cases from early test runs,
# normalized deterministically rather than trusting the model a second time.
EINHEIT_NORMALISIERUNG = {
    "m?": "m2", "mz": "m2", "m²": "m2", "m^2": "m2",
    "m3?": "m3", "m³": "m3", "m^3": "m3",
}


class OfferteMeta(BaseModel):
    lieferant: str | None = Field(None, description="Firma, die die Offerte ausstellt (Briefkopf/Unterschrift)")
    offerte_nr: str | None = None
    datum: str | None = None
    objekt: str | None = Field(None, description="Projekt-/Objektbezeichnung, z.B. 'Margrethenpark 8392 4/603 OSC'")
    zahlungskonditionen: str | None = None
    termin: str | None = None


class OffertePosition(BaseModel):
    position: int | None = Field(None, description="Positionsnummer aus der 'Position'-Spalte, falls vorhanden")
    bezeichnung: str = Field(..., description="Vollständiger Beschreibungstext der Position, inkl. Zeilen wie 'Haus G1'")
    menge: float | None = None
    einheit: str | None = Field(None, description="z.B. 'm2', 'Stk', 'pauschal'")
    einzelpreis: float | None = None
    gesamtpreis: float | None = None

    @field_validator("einheit")
    @classmethod
    def _normalisiere_einheit(cls, v: str | None) -> str | None:
        return EINHEIT_NORMALISIERUNG.get(v.strip(), v) if v else v


class OfferteTotals(BaseModel):
    total_brutto: float | None = None
    rabatt_prozent: float | None = None
    rabatt_betrag: float | None = None
    zwischentotal: float | None = None
    skonto_prozent: float | None = None
    skonto_betrag: float | None = None
    entsorgungsgebuehren: float | None = None
    total_netto: float | None = None
    mwst_prozent: float | None = None
    mwst_betrag: float | None = None
    total_netto_inkl_mwst: float | None = None


class Materialofferte(BaseModel):
    meta: OfferteMeta
    positions: list[OffertePosition]
    totals: OfferteTotals

    def check_plausibility(self, tolerance: float = 0.5) -> str | None:
        """Returns a warning message if the extraction looks wrong, else None.

        Sum of position totals must roughly match the brutto total -- catches extraction errors
        (wrong column, missed row) without aborting; callers decide whether to flag/re-run or
        accept the result.
        """
        if not self.positions and not any(v is not None for v in self.totals.model_dump().values()):
            return "no positions and no totals extracted -- PDF likely has no readable content"
        summe = sum(p.gesamtpreis for p in self.positions if p.gesamtpreis is not None)
        if self.totals.total_brutto is not None and abs(summe - self.totals.total_brutto) > tolerance:
            return f"sum of position totals {summe:.2f} != total_brutto {self.totals.total_brutto:.2f}"
        return None


EXTRACTION_SYSTEM_PROMPT = """\
Du extrahierst Daten aus einer Schweizer Bau-/Maler-Offerte (Materialofferte, im Anhang als PDF)
in das vorgegebene JSON-Schema.

Regeln:
- Übernimm Zahlen ohne Tausender-Apostroph, mit Punkt als Dezimaltrennzeichen (z.B. "16'773.75" -> 16773.75).
- Prozentangaben als reine Zahl ohne %-Zeichen (z.B. "2.00 %" -> 2.0).
- Jede Tabellenzeile mit eigenem Gesamtpreis (G-Preis) wird eine eigene Position, auch wenn sie zu einer
  übergeordneten Positionsnummer gehört (z.B. "Haus G1." und "Haus G2." unter Position 4/5).
- "bezeichnung" enthält den vollen Beschreibungstext der Position (mehrzeilig zusammengefasst).
- "einheit" auf einen festen Satz normalisieren: "m2", "m3", "Stk", "h" oder "pauschal" -- auch wenn das
  Quadrat-/Kubikzeichen im Dokument klein, hochgestellt oder schwer lesbar ist, aus dem Kontext (z.B.
  Flächenbeschichtung, Kubatur) ableiten, welche Einheit gemeint ist.
- Felder, die im Dokument fehlen, bleiben null.
- "Übertrag"-Zeilen (Seitenumbruch-Zwischensummen) sind keine eigenen Positionen und keine Totale -- ignorieren.
"""


async def extract_materialofferte(pdf_block: dict, llm) -> Materialofferte:
    """Extracts a Materialofferte PDF into the fixed schema above.

    `pdf_block` is `{"data": "<base64-encoded-pdf>"}`, same shape as `transcribe_pdf_to_text`.
    `llm` is a caller-supplied chat model; `llm.with_structured_output(Materialofferte)` is called
    here to build the actual model.
    """
    model = llm.with_structured_output(Materialofferte)
    return await model.ainvoke([
        {
            "role": "user",
            "content": [
                {"type": "text", "text": EXTRACTION_SYSTEM_PROMPT},
                {"type": "media", "mime_type": "application/pdf", "data": pdf_block["data"]},
            ],
        },
    ])
