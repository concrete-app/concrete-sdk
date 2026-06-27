"""Deterministic parser for Preisanfrage PDFs (Abacus/Excel export, one fixed template).

Unlike Werkvertrag (scanned, broken text layer -- needs LLM transcription) or Materialofferte
(one different layout per supplier -- needs an LLM to map onto a fixed schema), a Preisanfrage is
a single, digitally-generated PDF (Excel/.xlsm export) with a real text layer and a fixed
column/header layout. No LLM is involved here at all -- coordinate-based parsing with `pdfplumber`
is enough, and is more reliable than OCR/LLM transcription would be for a layout this regular.

The header block (Kommission/Lieferant/Projektleiter/...) is a *rotated* text field in the PDF.
`pdfplumber.extract_words()` doesn't group rotated characters into words (every letter comes back
individually); `extract_text()` reads them in the wrong order. Grouping characters by row (`top`)
and sorting by `x0` reconstructs the line correctly anyway, because the characters sit at the
correct on-screen position -- only their word-grouping flag is wrong. Label and value are then
split with a marker regex, exactly like Werkvertrag's "R" markers, just with plain-text labels.

The quantity table (`Pos. | Bezeichnung | Stk | L mm | B mm | H mm | m1 | m2 | m3`) is normal
upright text, so `extract_words()` works there and returns x0/x1 per word -- column boundaries are
derived from the header row itself rather than hardcoded pixel positions, since the page margin
shifts slightly between documents.

Calibrated against the Abacus export template that has exactly the columns in COLUMN_LABELS
(`Pos. | Bezeichnung | Stk | L mm | B mm | H mm | m1 | m2 | m3`). Abacus exports with additional
or differently-named columns (e.g. an extra "Bauuntergr." or "Nr." column) will raise a KeyError
in `_parse_body` rather than silently mis-parsing -- this is a layout-coverage gap inherited from
the original prototype, not a new behavior.
"""

from __future__ import annotations

import io
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import pdfplumber

LABELS = [
    "Kommission", "Druckdatum", "Lieferant", "Projektleiter", "Liefertermin",
    "Tel. direkt", "Lieferadresse", "E-Mail", "Bestellgruppe", "Baugruppe", "Qualität", "Avis", "Ablad",
]
LABEL_RE = re.compile("|".join(re.escape(l) for l in sorted(LABELS, key=len, reverse=True)))

COLUMN_LABELS = ["Pos.", "Bezeichnung", "Stk", "L mm", "B mm", "H mm", "m1", "m2", "m3"]
COLUMN_TO_FIELD = {
    "Pos.": "pos", "Stk": "stk", "L mm": "l_mm", "B mm": "b_mm", "H mm": "h_mm", "m1": "m1", "m2": "m2", "m3": "m3",
}
NUMBER_RE = re.compile(r"^-?\d{1,3}(?:'\d{3})*(?:\.\d+)?$")
ARTIKEL_RE = re.compile(r"\(Art\.\s*([\w.]+)\)")
FOOTER_RE = re.compile(r"\.xlsm|Seite\s*\d+\s*von\s*\d+", re.IGNORECASE)
GROUP_RE = re.compile(r"^G\d+$")
TOTAL_TOLERANZ = 0.05  # absorbs rounding drift in the source document (e.g. 210.29 vs. computed 210.30)


@dataclass
class PreisanfrageMeta:
    kommission: str | None = None
    druckdatum: str | None = None
    lieferant: str | None = None
    projektleiter: str | None = None
    liefertermin: str | None = None
    tel_direkt: str | None = None
    lieferadresse: str | None = None
    email: str | None = None
    bestellgruppe: str | None = None
    baugruppe: str | None = None  # some templates use "Baugruppe" instead of "Bestellgruppe"
    qualitaet: str | None = None
    avis: str | None = None
    ablad: str | None = None


@dataclass
class PreisanfragePosition:
    bezeichnung: str  # material description, incl. color/variant
    gruppe: str | None = None  # "G1"/"G2" -- building or variant code
    artikel_nr: str | None = None  # extracted from "(Art. 696)"
    pos: float | None = None
    stk: float | None = None
    l_mm: float | None = None
    b_mm: float | None = None
    h_mm: float | None = None
    m1: float | None = None  # linear meters -- in some templates appears before m2 (e.g. Schalungslisten)
    m2: float | None = None
    m3: float | None = None


@dataclass
class GruppenTotal:
    gruppe: str
    betrag: float


def _to_float(s: str) -> float:
    return float(s.replace("'", ""))


def _header_text_from_chars(page, top_cutoff: float) -> str:
    # Sorting purely by x0 breaks when neighboring fields' bounding boxes overlap by a few points
    # (e.g. "Hochdorf" + "E-Mail" -- the 'f' of "Hochdorf" sits slightly right of the 'E' of
    # "E-Mail"; a strict x0 sort would produce "HochdorEf-Mail"). The natural stream order isn't
    # reliable either: some value fields are drawn before their own label even though they sit
    # visually to its right (large x0 gap, no overlap). Coarse bucketing (10pt) + stable sort
    # combines both: at real column boundaries (large gap) it sorts by x0, while mini-overlaps
    # within the same bucket keep the -- there correct -- stream order.
    rows: dict[float, list[dict]] = {}
    for c in page.chars:
        if c["top"] >= top_cutoff:
            continue
        key = next((t for t in rows if abs(t - c["top"]) < 1.0), c["top"])
        rows.setdefault(key, []).append(c)
    lines = ["".join(c["text"] for c in sorted(rows[t], key=lambda c: round(c["x0"] / 10))) for t in sorted(rows)]
    return " ".join(lines)


def _rows_from_words(words: list[dict]) -> list[list[dict]]:
    rows: dict[float, list[dict]] = {}
    for w in words:
        key = next((t for t in rows if abs(t - w["top"]) < 1.0), w["top"])
        rows.setdefault(key, []).append(w)
    return [sorted(rows[t], key=lambda w: w["x0"]) for t in sorted(rows)]


def _detect_columns(header_row: list[dict]) -> dict[str, tuple[float, float]]:
    # Multi-word headers ("L mm") are reassembled by comparing the whitespace-free text against
    # COLUMN_LABELS; column x-positions come from this header row instead of hardcoded pixel
    # values, since the page margin shifts between documents.
    columns: dict[str, tuple[float, float]] = {}
    buffer_text, buffer_words = "", []
    # Also strips the period ("Pos." vs "Pos") -- some templates write the column header without one.
    targets = {c.replace(" ", "").replace(".", ""): c for c in COLUMN_LABELS}
    for w in header_row:
        buffer_text += w["text"]
        buffer_words.append(w)
        normalized = buffer_text.replace(".", "")
        if normalized in targets:
            columns[targets[normalized]] = (buffer_words[0]["x0"], buffer_words[-1]["x1"])
            buffer_text, buffer_words = "", []
    return columns


def _nearest_column(x1: float, columns: dict[str, tuple[float, float]]) -> str:
    # Classifies via the interval [own x0, next column's x0) that the value's right edge (x1)
    # falls into -- more robust than distance-to-anchor: for two narrow, closely-spaced columns
    # (e.g. "m1"/"m2") a value would otherwise be closer to the neighboring column's anchor even
    # though it structurally belongs to its own column.
    ordered = sorted(columns.items(), key=lambda kv: kv[1][0])
    for i, (name, _) in enumerate(ordered):
        next_x0 = ordered[i + 1][1][0] if i + 1 < len(ordered) else float("inf")
        if x1 < next_x0:
            return name
    return ordered[-1][0]


def _parse_meta(header_text: str) -> PreisanfrageMeta:
    matches = list(LABEL_RE.finditer(header_text))
    values: dict[str, str | None] = {}
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(header_text)
        values[m.group(0)] = header_text[start:end].strip() or None
    return PreisanfrageMeta(
        kommission=values.get("Kommission"), druckdatum=values.get("Druckdatum"),
        lieferant=values.get("Lieferant"), projektleiter=values.get("Projektleiter"),
        liefertermin=values.get("Liefertermin"), tel_direkt=values.get("Tel. direkt"),
        lieferadresse=values.get("Lieferadresse"), email=values.get("E-Mail"),
        bestellgruppe=values.get("Bestellgruppe"), baugruppe=values.get("Baugruppe"),
        qualitaet=values.get("Qualität"),
        avis=values.get("Avis"), ablad=values.get("Ablad"),
    )


def _parse_body(rows: list[list[dict]], columns: dict[str, tuple[float, float]]) -> tuple[
    list[PreisanfragePosition], list[GruppenTotal], float | None, dict[str, list[str]]
]:
    positions: list[PreisanfragePosition] = []
    gruppen_totale: list[GruppenTotal] = []
    gesamt_total: float | None = None
    notizen: dict[str, list[str]] = {}
    current_section: str | None = None
    current_group: str | None = None
    # After the (single) grand total, some templates have free-text notes with their own
    # numbering ("1 Zuschnitt...", "2 Preis...") -- their leading digit happens to sit in the
    # Pos. column position and would otherwise be misread as a new table row.
    table_done = False
    # "Bezeichnung" is left-aligned free text of arbitrary length (e.g. "...1 x am Bau...") -- a
    # lone digit in it must not be misread as an Stk quantity. Data values therefore only count
    # from the left edge of the Stk column onward. The Pos. column to the left of Bezeichnung is
    # exempt from this: some templates genuinely fill it (1, 2, 3, ...), making it a real data
    # column rather than a digit inside free text.
    pos_zone_end = columns["Bezeichnung"][0]
    data_zone_start = columns["Stk"][0]

    for row in rows:
        text = " ".join(w["text"] for w in row)
        if FOOTER_RE.search(text):
            continue

        if table_done:
            stripped = text.strip()
            if stripped.endswith(":"):
                current_section = stripped[:-1]
                notizen.setdefault(current_section, [])
            elif stripped:
                notizen.setdefault(current_section or "Allgemein", []).append(stripped)
            continue

        number_words = [
            w for w in row
            if NUMBER_RE.match(w["text"]) and (w["x0"] < pos_zone_end or w["x0"] >= data_zone_start)
        ]
        label_words = [w for w in row if w not in number_words]
        label_text = " ".join(w["text"] for w in label_words).strip()

        if not number_words:
            if label_text.endswith(":"):
                current_section = label_text[:-1]
                notizen.setdefault(current_section, [])
            elif GROUP_RE.match(label_text):
                current_group = label_text
            elif label_text:
                notizen.setdefault(current_section or "Allgemein", []).append(label_text)
            continue

        values = {
            COLUMN_TO_FIELD[_nearest_column(w["x1"], columns)]: _to_float(w["text"])
            for w in number_words
        }

        if label_text == "Total":
            betrag = values.get("m2") or next(iter(values.values()))
            if current_group:
                # Some templates have no group subtotals, just a single grand total at the end of
                # the document -- at that point `current_group` still holds the last group seen.
                # Checking plausibility against the first field present in this row (usually Stk,
                # since it's exact and unrounded) decides whether the sum belongs only to this
                # group or to everything seen so far.
                pruef_feld, pruef_wert = next(iter(values.items()))
                gruppen_summe = sum(
                    getattr(p, pruef_feld) for p in positions
                    if p.gruppe == current_group and getattr(p, pruef_feld) is not None
                )
                if abs(pruef_wert - gruppen_summe) < TOTAL_TOLERANZ:
                    gruppen_totale.append(GruppenTotal(current_group, betrag))
                else:
                    gesamt_total = betrag
                    table_done = True
                current_group = None
            else:
                gesamt_total = betrag
                table_done = True
            continue

        artikel_match = ARTIKEL_RE.search(label_text)
        positions.append(PreisanfragePosition(
            bezeichnung=label_text, gruppe=current_group,
            artikel_nr=artikel_match.group(1) if artikel_match else None,
            pos=values.get("pos"), stk=values.get("stk"), l_mm=values.get("l_mm"),
            b_mm=values.get("b_mm"), h_mm=values.get("h_mm"), m1=values.get("m1"),
            m2=values.get("m2"), m3=values.get("m3"),
        ))

    return positions, gruppen_totale, gesamt_total, notizen


class Preisanfrage:
    def __init__(self, meta: PreisanfrageMeta, positions: list[PreisanfragePosition],
                 gruppen_totale: list[GruppenTotal], gesamt_total: float | None,
                 notizen: dict[str, list[str]]):
        self.meta = meta
        self.positions = positions
        self.gruppen_totale = gruppen_totale
        self.gesamt_total = gesamt_total
        self.notizen = notizen

    @classmethod
    def from_pdf_bytes(cls, pdf_bytes: bytes) -> "Preisanfrage":
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            body_rows: list[list[dict]] = []
            header_text = ""
            columns: dict[str, tuple[float, float]] = {}
            for page in pdf.pages:
                page_rows = _rows_from_words(page.extract_words(use_text_flow=False, keep_blank_chars=False))
                # Some templates write the column header as "Pos" without a period instead of "Pos.".
                header_row = next((r for r in page_rows
                                    if "".join(w["text"] for w in r).replace(".", "").startswith("PosBezeichnung")), None)
                if header_row is not None:
                    header_text = _header_text_from_chars(page, top_cutoff=header_row[0]["top"])
                    columns = _detect_columns(header_row)
                    body_rows.extend(r for r in page_rows
                                      if r is not header_row and r[0]["top"] > header_row[0]["top"])
                else:
                    body_rows.extend(page_rows)

        if not columns:
            raise ValueError("Table header 'Pos. Bezeichnung ...' not found")

        meta = _parse_meta(header_text)
        positions, gruppen_totale, gesamt_total, notizen = _parse_body(body_rows, columns)
        return cls(meta, positions, gruppen_totale, gesamt_total, notizen)

    @classmethod
    def from_pdf(cls, pdf_path: str | Path) -> "Preisanfrage":
        return cls.from_pdf_bytes(Path(pdf_path).read_bytes())

    def by_gruppe(self, gruppe: str) -> list[PreisanfragePosition]:
        return [p for p in self.positions if p.gruppe == gruppe]

    def check_plausibility(self, tolerance: float = TOTAL_TOLERANZ) -> str | None:
        """Returns a warning message if the extraction looks wrong, else None.

        Sum of position values per group must match that group's total, and the sum of group
        totals must match the grand total -- catches both parsing errors (wrong column) and
        column mix-ups.
        """
        for gt in self.gruppen_totale:
            summe = sum(p.m2 for p in self.by_gruppe(gt.gruppe) if p.m2)
            if abs(summe - gt.betrag) >= tolerance:
                return f"gruppe {gt.gruppe}: sum {summe:.2f} != gruppentotal {gt.betrag:.2f}"
        if self.gruppen_totale and self.gesamt_total is not None:
            summe = sum(gt.betrag for gt in self.gruppen_totale)
            if abs(summe - self.gesamt_total) >= tolerance:
                return f"sum of gruppentotale {summe:.2f} != gesamttotal {self.gesamt_total:.2f}"
        return None

    def to_dataframe(self):
        import pandas as pd
        return pd.DataFrame([vars(p) for p in self.positions])

    def to_dict(self) -> dict:
        return {
            "meta": asdict(self.meta),
            "positionen": [asdict(p) for p in self.positions],
            "gruppen_totale": [asdict(g) for g in self.gruppen_totale],
            "gesamt_total": self.gesamt_total,
            "notizen": self.notizen,
        }

    def export_json(self, path: str | Path) -> Path:
        path = Path(path)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))
        return path
