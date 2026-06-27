"""Deterministic Werkvertrag/Angebot (Leistungsverzeichnis) parser.

Built from six real documents: two signed Werkvertraege and four Angebot (Ausschreibung) forms.
Both document types share the same NPK-based Leistungsverzeichnis structure (chapter -> group ->
subgroup -> leaf position), but an Angebot is a blank tender form -- quantity/unit come from the
LV spec itself and are always present, while unit price / total price are placeholder dot-runs
("....................") waiting for a contractor to fill in, and contract-level fields like
Brutto/Netto/Werkvertrag Nr. simply don't exist yet. Every field below is therefore Optional and
missing gracefully (None) rather than raising, except the internal consistency check on Position
(menge * einzelpreis == gesamtpreis), which only runs when all three are actually present.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path


def _to_float(s: str | None) -> float | None:
    """Parses a Swiss-formatted number ("1'234.56"). Returns None for blanks/placeholder dot-runs
    -- an Angebot renders an unfilled amount as dots, not as a number, and that absence is itself
    meaningful (this field hasn't been priced yet), not a parsing failure."""
    if not s:
        return None
    s = s.strip().strip("*").strip()
    if not s or not re.search(r"\d", s):
        return None
    try:
        return float(s.replace("'", "").replace(",", "."))
    except ValueError:
        return None


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%d.%m.%Y").date()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Beteiligte:
    # Nicht jede Rolle ist in jedem Dokument vorhanden -- ein Angebot (vor Vergabe) hat z.B. noch
    # keinen Unternehmer, und nicht jedes Werkvertrag-Template fuehrt einen separaten Architekten.
    bauherr: str | None = None
    architekt: str | None = None
    bauleitung: str | None = None
    holzbauingenieur: str | None = None
    unternehmer: str | None = None


@dataclass
class Vertragsdetails:
    angebot_vom: date | None = None    # nur im Werkvertrag (verweist auf ein bereits eingereichtes Angebot)
    # Freitext, kein Klausel-Code -- variiert zwischen Vertraegen ("Gemaess beiliegendem
    # Terminplan", "August 2026", "Elementmontage ab 30.09.2024", ...)
    arbeitsbeginn: str | None = None
    preisstand: str | None = None      # Freitext, ebenso variabel ("Teuerungsausgleich nach Holzbauindex Schweiz", "Festpreis bis Bauvollendung", ...)
    garantieart: str | None = None     # Freitext, kann "X Jahre" direkt enthalten


@dataclass
class KonditionenZeile:
    label: str
    prozent: float | None
    betrag: float | None       # None in einem Angebot -- noch nicht ausgefuellter Platzhalter


@dataclass
class Konditionen:
    zeilen: list[KonditionenZeile] = field(default_factory=list)
    zahlungsfrist_tage: int | None = None


@dataclass
class Vorbedingungen:
    garantiefrist_jahre: int | None = None
    konventionalstrafe: bool = False
    vorauszahlungsgarantie: bool = False


@dataclass
class Position:
    number: str                        # vollqualifiziert, z.B. "211.111"
    level: str                         # "chapter" | "group" | "subgroup" | "leaf"
    title: str
    text: str
    parent_number: str | None = None
    is_custom: bool = False            # trug die "R"-Markierung (weicht vom Standard-NPK ab) -- nicht jedes Template markiert das
    is_eventual: bool = False
    refers_to: list[str] = field(default_factory=list)
    menge: float | None = None         # nur auf "leaf"-Ebene gesetzt
    einheit: str | None = None
    einzelpreis: float | None = None   # None in einem Angebot -- noch nicht ausgefuellt
    gesamtpreis: float | None = None

    def __post_init__(self):
        if self.menge is not None and self.einzelpreis is not None and self.gesamtpreis is not None:
            erwartet = self.menge * self.einzelpreis
            if abs(erwartet - abs(self.gesamtpreis)) > 0.5:
                raise ValueError(
                    f"Position {self.number}: gesamtpreis {self.gesamtpreis} passt nicht zu "
                    f"menge*einzelpreis = {erwartet}"
                )


@dataclass
class Werkvertrag:
    name: str | None = None            # "Werkvertrag" oder "Ausschreibung und Angebot"
    nr: str | None = None
    datum: date | None = None          # "vom DD.MM.YYYY" -- nur im Werkvertrag-Titel vorhanden
    projekt_nr: str | None = None
    projekt_bezeichnung: str | None = None
    objekt: str | None = None
    auftragssumme_brutto: float | None = None
    auftragssumme_netto: float | None = None
    beteiligte: Beteiligte = field(default_factory=Beteiligte)
    vertragsdetails: Vertragsdetails = field(default_factory=Vertragsdetails)
    konditionen: Konditionen = field(default_factory=Konditionen)
    vorbedingungen: Vorbedingungen = field(default_factory=Vorbedingungen)
    positionen: list[Position] = field(default_factory=list)

    def to_json(self, output_path: str | Path) -> Path:
        path = Path(output_path)
        path.write_text(json.dumps(asdict(self), default=str, indent=2, ensure_ascii=False))
        return path


# ---------------------------------------------------------------------------
# LV hierarchy parsing (chapter/group/subgroup/leaf markers)
# ---------------------------------------------------------------------------

# "R" davor ist OPTIONAL -- manche Templates markieren JEDE Position mit "R" (auch unveraenderten
# Standard-NPK-Text), andere nur die tatsaechlich individuell angepassten (Standard-NPK-Kapitel
# bleiben dort ohne "R"). Beide Verhalten kommen in den echten Dokumenten vor.
#
# Ohne das Pflicht-"R" muessen wir Mengenzeilen ("390 m2 12.00 4'680.00") explizit ausschliessen,
# da sie sonst als Kapitelmarker ("390") fehlinterpretiert wuerden -- der zweite Negative-Lookahead
# schliesst genau die Form <Zahl> <kurze Einheit> <Zahl> aus.
MARKER_RE = re.compile(
    r"^(?P<r>R\s*)?"
    r"(?:(?P<continuation>\d{2,4}\.\d{1,4})"
    r"|\.\s*(?P<sub>\d{1,4})\b"
    r"|(?P<chapter>\d{2,4})(?![.\d])(?!\s*[A-Za-zÄÖÜäöü]{1,3}\d{0,1}\s+[\d'.]))",
    re.MULTILINE,
)


def _level_for_suffix(suffix: str) -> str:
    if suffix.endswith("00"):
        return "group"
    if suffix.endswith("0"):
        return "subgroup"
    return "leaf"


REFERS_TO_RE = re.compile(r"Pos\.?\s*(\d{2,4})\.(\d{1,4})(?:\s*-\s*(\d{1,4}))?")


def _extract_refers_to(text: str) -> list[str]:
    refs: list[str] = []
    for m in REFERS_TO_RE.finditer(text):
        chapter, start, end = m.group(1), m.group(2), m.group(3)
        refs.append(f"{chapter}.{start}")
        if end:
            refs.append(f"{chapter}.{end}")
    return refs


QUANTITY_RE = re.compile(
    r"(?P<qty>\d{1,3}(?:'\d{3})*(?:\.\d+)?)\s+"
    r"(?P<unit>[A-Za-zÄÖÜäöü]{1,3}\d?)\s+"
    r"(?:(?P<price>\d{1,3}(?:'\d{3})*\.\d{2})\s*"
    r"(?P<open>\()?\s*(?P<total>\d{1,3}(?:'\d{3})*\.\d{2})\s*(?P<close>\))?"
    r"|(?P<placeholder>\.{4,}[ \t]*\.{4,}))"
)


def _extract_quantity(text: str) -> tuple[float | None, str | None, float | None, float | None]:
    # Bei mehreren Treffern im Textblock (z.B. Mengenangabe in einer Erklaerung, dann die echte
    # Mengenzeile am Ende der Position) ist der LETZTE Treffer zuverlaessig die echte Mengenzeile.
    for m in reversed(list(QUANTITY_RE.finditer(text))):
        qty = _to_float(m.group("qty"))
        unit = m.group("unit")
        if m.group("placeholder"):
            return qty, unit, None, None  # Angebot: Menge/Einheit aus der LV-Vorlage, Preis noch nicht ausgefuellt
        price = _to_float(m.group("price"))
        total = _to_float(m.group("total"))
        if m.group("open") or m.group("close"):
            total = -total  # Minderpreis steht in Klammern im Original
        if qty is not None and price is not None and total is not None and abs(qty * price - abs(total)) < 0.5:
            return qty, unit, price, total
    return None, None, None, None


def parse_positions(text: str) -> list[Position]:
    matches = list(MARKER_RE.finditer(text))
    positions: dict[str, Position] = {}
    order: list[str] = []
    current_chapter: str | None = None
    active_group: str | None = None
    active_subgroup: str | None = None

    for i, m in enumerate(matches):
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        is_custom = bool(m.group("r"))

        if m.group("chapter"):
            number = m.group("chapter")
            current_chapter = number
            active_group = active_subgroup = None
            level, parent = "chapter", None
        elif m.group("continuation"):
            number = m.group("continuation")
            current_chapter = number.split(".")[0]
            level = _level_for_suffix(number.split(".", 1)[1])
            parent = active_subgroup or active_group or current_chapter
        else:
            if current_chapter is None:
                continue  # Sub-Marker ohne vorherigen Kapitelkontext -- ueberspringen statt zu raten
            number = f"{current_chapter}.{m.group('sub')}"
            level = _level_for_suffix(m.group("sub"))
            parent = active_subgroup or active_group or current_chapter

        if level == "group":
            active_group, active_subgroup = number, None
        elif level == "subgroup":
            active_subgroup = number

        title = body.split("\n", 1)[0].strip() if body else ""
        is_eventual = "eventual" in body.lower()
        menge = einheit = einzelpreis = gesamtpreis = None
        if level == "leaf":
            menge, einheit, einzelpreis, gesamtpreis = _extract_quantity(body)

        if number in positions:
            # Fortsetzung nach Seitenumbruch -- Text anhaengen statt doppelten Knoten zu erzeugen
            positions[number].text += "\n\n" + body
            continue

        positions[number] = Position(
            number=number, level=level, title=title, text=body,
            parent_number=parent, is_custom=is_custom,
            is_eventual=is_eventual, refers_to=_extract_refers_to(body) if is_eventual else [],
            menge=menge, einheit=einheit, einzelpreis=einzelpreis, gesamtpreis=gesamtpreis,
        )
        order.append(number)

    return [positions[n] for n in order]


# ---------------------------------------------------------------------------
# Header / metadata field extraction
# ---------------------------------------------------------------------------

TITLE_RE = re.compile(
    r"Werkvertrag Nr\.\s*(?P<wv_nr>\d+)(?:\s*vom\s*(?P<wv_datum>\d{2}\.\d{2}\.\d{4}))?"
    r"|(?:Ausschreibung und )?Angebot Nr\.\s*(?P<ang_nr>\d+)"
)
# "Projekt:" kann die Nummer auf derselben Zeile haben ("Projekt: 2101") oder die Nummer auf der
# naechsten Zeile, gefolgt von der Bezeichnung auf der Zeile danach -- beide Formen kommen vor.
PROJEKT_RE = re.compile(r"Projekt:\s*\n?\s*(\d+)\s*\n+([^\n]+)")
OBJEKT_RE = re.compile(r"Objekt:\s*\n*\s*([^\n]+)")
ANGEBOT_VOM_RE = re.compile(r"Angebot vom:\s*\n*\s*(\d{2}\.\d{2}\.\d{4})")
ARBEITSBEGINN_RE = re.compile(r"Arbeitsbeginn:\s*\n*\s*([^\n]+)")
PREISSTAND_RE = re.compile(r"Preisstand:\s*\n*\s*([^\n]+)")
GARANTIEART_RE = re.compile(r"Garantieart:\s*\n*\s*([^\n]+)")

BETEILIGTE_LABELS = {
    "bauherr": "Bauherr",
    "architekt": "Architekt",
    "bauleitung": "Bauleitung",
    "holzbauingenieur": "Holzbauingenieur",
    "unternehmer": "Unternehmer",
}


def _match_group(pattern: re.Pattern, text: str, group: int = 1) -> str | None:
    m = pattern.search(text)
    return m.group(group).strip() if m else None


def _extract_beteiligte(header: str) -> Beteiligte:
    kwargs = {}
    for field_name, label in BETEILIGTE_LABELS.items():
        pattern = re.compile(rf"(?:##\s*)?{label}:\s*\n+([^\n]+)")
        kwargs[field_name] = _match_group(pattern, header)
    return Beteiligte(**kwargs)


def _extract_vertragsdetails(header: str) -> Vertragsdetails:
    return Vertragsdetails(
        angebot_vom=_parse_date(_match_group(ANGEBOT_VOM_RE, header)),
        arbeitsbeginn=_match_group(ARBEITSBEGINN_RE, header),
        preisstand=_match_group(PREISSTAND_RE, header),
        garantieart=_match_group(GARANTIEART_RE, header),
    )


def _extract_vorbedingungen(text: str) -> Vorbedingungen:
    garantie_match = re.search(r"Garantie\D{0,40}?(\d+)\s*Jahre", text, re.IGNORECASE)
    keine_vorauszahlung = re.search(r"Keine\s*Vorauszahlungen", text, re.IGNORECASE) is not None
    return Vorbedingungen(
        garantiefrist_jahre=int(garantie_match.group(1)) if garantie_match else None,
        konventionalstrafe="konventionalstrafe" in text.lower(),
        vorauszahlungsgarantie=not keine_vorauszahlung and "vorauszahlung" in text.lower(),
    )


def _extract_meta(text: str) -> tuple[str | None, str | None, date | None, str | None, str | None, str | None]:
    header = text[:2500]
    title = TITLE_RE.search(header)
    if title and title.group("wv_nr"):
        name, nr, datum = "Werkvertrag", title.group("wv_nr"), _parse_date(title.group("wv_datum"))
    elif title and title.group("ang_nr"):
        name, nr, datum = "Ausschreibung und Angebot", title.group("ang_nr"), None
    else:
        name = nr = datum = None

    projekt_nr = projekt_bezeichnung = None
    projekt = PROJEKT_RE.search(header)
    if projekt:
        projekt_nr, projekt_bezeichnung = projekt.group(1), projekt.group(2).strip()

    objekt = _match_group(OBJEKT_RE, header)
    return name, nr, datum, projekt_nr, projekt_bezeichnung, objekt


# ---------------------------------------------------------------------------
# Konditionen table
# ---------------------------------------------------------------------------

ZAHLUNGSFRIST_RE = re.compile(r"Zahlungsfrist\s*(\d+)\s*Tage")


def _extract_konditionen(text: str) -> Konditionen:
    # Tabellenzeilen sind nicht immer einheitlich mit Fuehrungs-/Schluss-Pipe formatiert (manche
    # Transkriptionen rendern "Brutto | | 123.45 |", andere "| Brutto | | 123.45 |") -- daher wird
    # auf "|" getrennt statt ein striktes Pipe-an-Pipe-Pattern vorauszusetzen. Markdown-Bold
    # ("**Brutto**") wird durch das Strip von "*" in _to_float/Label-Bereinigung neutralisiert.
    start = text.find("Konditionen")
    if start == -1:
        return Konditionen()
    block = text[start:start + 2500]

    zeilen: list[KonditionenZeile] = []
    zahlungsfrist_tage = None
    for line in block.splitlines():
        line = line.strip()
        if "|" not in line or set(line) <= {"|", "-", ":", " "}:
            continue
        cells = [c.strip().strip("*").strip() for c in line.strip("|").split("|")]
        label = cells[0] if cells else ""
        if not label or label.lower() in ("bezeichnung", ""):
            continue
        prozent = betrag = None
        rest_parts: list[str] = []
        for c in cells[1:]:
            if not c:
                continue
            if c.rstrip().endswith("%") or re.fullmatch(r"\.+\s*%", c):
                prozent = _to_float(c.rstrip("% ").strip())
            elif betrag is None and re.search(r"\d|\.{4,}", c):
                betrag = _to_float(c)
            else:
                rest_parts.append(c)
        if betrag is None and prozent is None and not rest_parts:
            continue
        zeilen.append(KonditionenZeile(label=label, prozent=prozent, betrag=betrag))
        frist = ZAHLUNGSFRIST_RE.search(" ".join(rest_parts))
        if frist:
            zahlungsfrist_tage = int(frist.group(1))

    return Konditionen(zeilen=zeilen, zahlungsfrist_tage=zahlungsfrist_tage)


def _auftragssumme_from_konditionen(konditionen: Konditionen) -> tuple[float | None, float | None]:
    # Zuverlaessiger als ein Free-Text-Regex auf die Kopfzeile ("Auftragssumme ... Brutto ... Netto
    # ..." existiert nicht in jedem Template) -- die Konditionen-Tabelle hat in jedem der sechs
    # untersuchten Dokumente eine "Brutto"-Zeile und endet immer mit der finalen "Netto"-Zeile.
    brutto = next((z.betrag for z in konditionen.zeilen if z.label.lower() == "brutto"), None)
    netto_zeilen = [z for z in konditionen.zeilen if z.label.lower().startswith("netto")]
    netto = netto_zeilen[-1].betrag if netto_zeilen else None
    return brutto, netto


# ---------------------------------------------------------------------------
# WerkvertragParser
# ---------------------------------------------------------------------------


class WerkvertragParser:
    def __init__(self, text: str):
        self.text = text

    def parse(self) -> Werkvertrag:
        text = self.text
        name, nr, datum, projekt_nr, projekt_bezeichnung, objekt = _extract_meta(text)
        konditionen = _extract_konditionen(text)
        brutto, netto = _auftragssumme_from_konditionen(konditionen)

        return Werkvertrag(
            name=name,
            nr=nr,
            datum=datum,
            projekt_nr=projekt_nr,
            projekt_bezeichnung=projekt_bezeichnung,
            objekt=objekt,
            auftragssumme_brutto=brutto,
            auftragssumme_netto=netto,
            beteiligte=_extract_beteiligte(text[:3000]),
            vertragsdetails=_extract_vertragsdetails(text[:3000]),
            konditionen=konditionen,
            vorbedingungen=_extract_vorbedingungen(text),
            positionen=parse_positions(text),
        )
