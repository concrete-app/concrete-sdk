"""Deterministic Werkvertrag/Angebot (Leistungsverzeichnis) parser.

Built from six real documents: two signed Werkvertraege and four Angebot (Ausschreibung) forms.
Both document types share the same NPK-based Leistungsverzeichnis structure (chapter -> group ->
subgroup -> leaf position), but an Angebot is a blank tender form -- quantity/unit come from the
LV spec itself and are always present, while unit price / total price are placeholder dot-runs
("....................") waiting for a contractor to fill in, and header fields like Brutto/Netto/
Werkvertrag Nr. simply don't exist yet. Every field below is therefore Optional and missing
gracefully (None) rather than raising, except the internal consistency check on Position
(menge * einzelpreis == gesamtpreis), which only runs when all three are actually present.

One parser class per document section, each responsible for exactly one piece of the model --
`WerkvertragParser` only composes them.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path


def parse_swiss_number(value: str | None) -> float | None:
    """Parses a Swiss-formatted number ("1'234.56"). Returns None for blanks/placeholder dot-runs
    -- an Angebot renders an unfilled amount as dots, not as a number, and that absence is itself
    meaningful (this field hasn't been priced yet), not a parsing failure."""
    if not value:
        return None
    cleaned = value.strip().strip("*").strip()
    if not cleaned or not re.search(r"\d", cleaned):
        return None
    try:
        return float(cleaned.replace("'", "").replace(",", "."))
    except ValueError:
        return None


def parse_swiss_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%d.%m.%Y").date()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Dokumentkopf:
    name: str | None = None        # "Werkvertrag" oder "Ausschreibung und Angebot"
    nr: str | None = None
    datum: date | None = None      # "vom DD.MM.YYYY" -- nur im Werkvertrag-Titel vorhanden
    projekt_nr: str | None = None
    projekt_bezeichnung: str | None = None
    objekt: str | None = None


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

    @property
    def brutto(self) -> float | None:
        for zeile in self.zeilen:
            if zeile.label.lower() == "brutto":
                return zeile.betrag
        return None

    @property
    def netto(self) -> float | None:
        # Manche Templates haengen dem letzten "Netto"-Label einen Zusatz an ("Netto Akkord",
        # "Netto Pauschal") -- "startswith" deckt beide Schreibweisen ab. Falls mehrere Netto-
        # Zeilen vorkommen (z.B. Zwischenstand + Final), ist die letzte die massgebende.
        netto_zeilen = [z for z in self.zeilen if z.label.lower().startswith("netto")]
        return netto_zeilen[-1].betrag if netto_zeilen else None


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
    material: str | None = None        # spaeter vom LLM angereichert (siehe material.py), nicht vom Parser

    def __post_init__(self) -> None:
        if self.menge is not None and self.einzelpreis is not None and self.gesamtpreis is not None:
            erwartet = self.menge * self.einzelpreis
            if abs(erwartet - abs(self.gesamtpreis)) > 0.5:
                raise ValueError(
                    f"Position {self.number}: gesamtpreis {self.gesamtpreis} passt nicht zu "
                    f"menge*einzelpreis = {erwartet}"
                )


@dataclass
class Werkvertrag:
    kopf: Dokumentkopf = field(default_factory=Dokumentkopf)
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
# Section parsers
# ---------------------------------------------------------------------------


class MetaParser:
    """Parses the document title, Werkvertrag/Angebot-Nr, Projekt and Objekt."""

    TITLE_PATTERN = re.compile(
        r"Werkvertrag Nr\.\s*(?P<werkvertrag_nr>\d+)(?:\s*vom\s*(?P<werkvertrag_datum>\d{2}\.\d{2}\.\d{4}))?"
        r"|(?:Ausschreibung und )?Angebot Nr\.\s*(?P<angebot_nr>\d+)"
    )
    # "Projekt:" kann die Nummer auf derselben Zeile haben ("Projekt: 2101") oder die Nummer auf
    # der naechsten Zeile, gefolgt von der Bezeichnung auf der Zeile danach -- beide Formen kommen vor.
    PROJEKT_PATTERN = re.compile(r"Projekt:\s*\n?\s*(\d+)\s*\n+([^\n]+)")
    OBJEKT_PATTERN = re.compile(r"Objekt:\s*\n*\s*([^\n]+)")

    def parse(self, header: str) -> Dokumentkopf:
        name, nr, datum = self._parse_title(header)
        projekt_nr, projekt_bezeichnung = self._parse_projekt(header)
        return Dokumentkopf(
            name=name,
            nr=nr,
            datum=datum,
            projekt_nr=projekt_nr,
            projekt_bezeichnung=projekt_bezeichnung,
            objekt=self._match(self.OBJEKT_PATTERN, header),
        )

    def _parse_title(self, header: str) -> tuple[str | None, str | None, date | None]:
        match = self.TITLE_PATTERN.search(header)
        if match is None:
            return None, None, None
        if match.group("werkvertrag_nr"):
            return "Werkvertrag", match.group("werkvertrag_nr"), parse_swiss_date(match.group("werkvertrag_datum"))
        return "Ausschreibung und Angebot", match.group("angebot_nr"), None

    def _parse_projekt(self, header: str) -> tuple[str | None, str | None]:
        match = self.PROJEKT_PATTERN.search(header)
        if match is None:
            return None, None
        return match.group(1), match.group(2).strip()

    @staticmethod
    def _match(pattern: re.Pattern, text: str) -> str | None:
        match = pattern.search(text)
        return match.group(1).strip() if match else None


class BeteiligteParser:
    """Parses the four-to-five named parties (Bauherr, Architekt, Bauleitung,
    Holzbauingenieur, Unternehmer) from the document header."""

    ROLE_PATTERNS = {
        "bauherr": re.compile(r"(?:##\s*)?Bauherr:\s*\n+([^\n]+)"),
        "architekt": re.compile(r"(?:##\s*)?Architekt:\s*\n+([^\n]+)"),
        "bauleitung": re.compile(r"(?:##\s*)?Bauleitung:\s*\n+([^\n]+)"),
        "holzbauingenieur": re.compile(r"(?:##\s*)?Holzbauingenieur:\s*\n+([^\n]+)"),
        "unternehmer": re.compile(r"(?:##\s*)?Unternehmer:\s*\n+([^\n]+)"),
    }

    def parse(self, header: str) -> Beteiligte:
        rollen = {feld: self._match(pattern, header) for feld, pattern in self.ROLE_PATTERNS.items()}
        return Beteiligte(**rollen)

    @staticmethod
    def _match(pattern: re.Pattern, header: str) -> str | None:
        match = pattern.search(header)
        return match.group(1).strip() if match else None


class VertragsdetailsParser:
    """Parses Angebot vom / Arbeitsbeginn / Preisstand / Garantieart -- all free text, since
    real contracts phrase these differently rather than picking from a fixed clause list."""

    ANGEBOT_VOM_PATTERN = re.compile(r"Angebot vom:\s*\n*\s*(\d{2}\.\d{2}\.\d{4})")
    ARBEITSBEGINN_PATTERN = re.compile(r"Arbeitsbeginn:\s*\n*\s*([^\n]+)")
    PREISSTAND_PATTERN = re.compile(r"Preisstand:\s*\n*\s*([^\n]+)")
    GARANTIEART_PATTERN = re.compile(r"Garantieart:\s*\n*\s*([^\n]+)")

    def parse(self, header: str) -> Vertragsdetails:
        return Vertragsdetails(
            angebot_vom=parse_swiss_date(self._match(self.ANGEBOT_VOM_PATTERN, header)),
            arbeitsbeginn=self._match(self.ARBEITSBEGINN_PATTERN, header),
            preisstand=self._match(self.PREISSTAND_PATTERN, header),
            garantieart=self._match(self.GARANTIEART_PATTERN, header),
        )

    @staticmethod
    def _match(pattern: re.Pattern, header: str) -> str | None:
        match = pattern.search(header)
        return match.group(1).strip() if match else None


class KonditionenParser:
    """Parses the Konditionen table (Brutto -> Rabatt -> ... -> Netto).

    Table rows aren't formatted consistently between documents -- some have a leading/trailing
    "|", some don't -- so rows are split on "|" rather than matched against a strict pipe-bounded
    pattern. A row is only kept if it has a genuine value cell (a percentage, a number, or an
    Angebot's unfilled dot-run placeholder); otherwise it's most likely an unrelated line (e.g. a
    company contact footer) that happened to contain a "|" and land in the same text window.
    """

    PAYMENT_TERM_PATTERN = re.compile(r"Zahlungsfrist\s*(\d+)\s*Tage")
    HEADER_LABELS = {"", "bezeichnung"}

    def parse(self, text: str) -> Konditionen:
        block = self._find_block(text)
        if block is None:
            return Konditionen()

        zeilen: list[KonditionenZeile] = []
        zahlungsfrist_tage: int | None = None
        for line in block.splitlines():
            zeile, payment_term = self._parse_row(line)
            if zeile is not None:
                zeilen.append(zeile)
            if payment_term is not None:
                zahlungsfrist_tage = payment_term

        return Konditionen(zeilen=zeilen, zahlungsfrist_tage=zahlungsfrist_tage)

    @staticmethod
    def _find_block(text: str) -> str | None:
        start = text.find("Konditionen")
        if start == -1:
            return None
        return text[start:start + 2500]

    def _parse_row(self, line: str) -> tuple[KonditionenZeile | None, int | None]:
        line = line.strip()
        if "|" not in line or set(line) <= {"|", "-", ":", " "}:
            return None, None

        cells = [cell.strip().strip("*").strip() for cell in line.strip("|").split("|")]
        label = cells[0] if cells else ""
        if label.lower() in self.HEADER_LABELS:
            return None, None

        prozent, betrag, has_value_cell, rest = self._parse_value_cells(cells[1:])
        if not has_value_cell:
            return None, None

        payment_term_match = self.PAYMENT_TERM_PATTERN.search(" ".join(rest))
        payment_term = int(payment_term_match.group(1)) if payment_term_match else None
        return KonditionenZeile(label=label, prozent=prozent, betrag=betrag), payment_term

    @staticmethod
    def _parse_value_cells(cells: list[str]) -> tuple[float | None, float | None, bool, list[str]]:
        prozent: float | None = None
        betrag: float | None = None
        has_value_cell = False
        rest: list[str] = []
        for cell in cells:
            if not cell:
                continue
            if cell.endswith("%") or re.fullmatch(r"\.+\s*%", cell):
                prozent = parse_swiss_number(cell.rstrip("% ").strip())
                has_value_cell = True
            elif re.fullmatch(r"\.{4,}", cell) or re.search(r"\d", cell):
                has_value_cell = True
                if betrag is None:
                    betrag = parse_swiss_number(cell)
            else:
                rest.append(cell)
        return prozent, betrag, has_value_cell, rest


class VorbedingungenParser:
    """Parses Garantiefrist (years), Konventionalstrafe and Vorauszahlungsgarantie."""

    GARANTIEFRIST_PATTERN = re.compile(r"Garantie\D{0,40}?(\d+)\s*Jahre", re.IGNORECASE)
    KEINE_VORAUSZAHLUNG_PATTERN = re.compile(r"Keine\s*Vorauszahlungen", re.IGNORECASE)

    def parse(self, text: str) -> Vorbedingungen:
        garantiefrist_match = self.GARANTIEFRIST_PATTERN.search(text)
        keine_vorauszahlung = self.KEINE_VORAUSZAHLUNG_PATTERN.search(text) is not None
        text_lower = text.lower()
        return Vorbedingungen(
            garantiefrist_jahre=int(garantiefrist_match.group(1)) if garantiefrist_match else None,
            konventionalstrafe="konventionalstrafe" in text_lower,
            vorauszahlungsgarantie=not keine_vorauszahlung and "vorauszahlung" in text_lower,
        )


class PositionParser:
    """Walks the Leistungsverzeichnis and builds the chapter -> group -> subgroup -> leaf tree.

    "R" before a marker is OPTIONAL -- some templates mark every position with "R" (even
    unmodified standard NPK text), others only the ones actually customized (standard-NPK
    chapters stay unmarked). Both behaviours occur in the real documents this was built against.

    Without a mandatory "R", several text shapes need to be explicitly excluded, since they're
    syntactically indistinguishable from a real marker:
      - dates ("07.05.2024") look identical to a continuation marker ("211.112")
      - Bauablaufplan/Gantt rows ("112.8 Rueckbau ... Mon 06.11.23 Fre 23.02.24") use the same
        "<code>.<digit>" shape as a real position
      - quantity lines ("390 m2 12.00 4'680.00") look like a bare chapter number at line start
      - postal codes ("6005 Luzern") look like a bare 4-digit chapter number -- every bare
        (non-continuation) 4-digit match across all six source documents turned out to be a
        postal code, never a real NPK code, so the bare-chapter alternative is restricted to
        2-3 digits. A genuinely 4-digit NPK code (e.g. "8330.111") always appears via the
        continuation form (chapter+dot+sub together), which is unaffected by this restriction.
    """

    # Lookahead vor der Alternation prueft, ob hier ein vollstaendiges Tag.Monat.Jahr-Datum steht
    # (1-2-stellige Tag/Monat, 1-4-stelliges Jahr) -- ein echter NPK-Code hat nie ein 1-2-stelliges
    # erstes Segment, daher kein Fehlalarm bei echten Codes. Ein Lookahead NACH der Continuation-
    # Gruppe waere hier nicht zuverlaessig, da die Regex-Engine sonst auf weniger Ziffern in der
    # zweiten Gruppe backtrackt und die Ausschlussregel umgeht.
    MARKER_PATTERN = re.compile(
        r"^(?!\d{1,2}\.\d{1,2}\.\d{1,4}\b)(?P<r>R\s*)?"
        r"(?:(?P<continuation>\d{2,4}\.\d{1,4})"
        r"|\.\s*(?P<sub>\d{1,4})\b"
        r"|(?P<chapter>\d{2,3})(?![.\d])(?!\s*[A-Za-zÄÖÜäöü]{1,3}\d{0,1}\s+[\d'.]))",
        re.MULTILINE,
    )
    GANTT_NOISE_PATTERN = re.compile(
        r"(Mon|Die|Mi|Don|Fre)\.?\s+\d{1,2}\.\d{1,2}\.\d{2,4}.*(Mon|Die|Mi|Don|Fre)\.?\s+\d{1,2}\.\d{1,2}\.\d{2,4}"
    )
    QUANTITY_PATTERN = re.compile(
        r"(?P<qty>\d{1,3}(?:'\d{3})*(?:\.\d+)?)\s+"
        r"(?P<unit>[A-Za-zÄÖÜäöü]{1,3}\d?)\s+"
        r"(?:(?P<price>\d{1,3}(?:'\d{3})*\.\d{2})\s*"
        r"(?P<open>\()?\s*(?P<total>\d{1,3}(?:'\d{3})*\.\d{2})\s*(?P<close>\))?"
        r"|(?P<placeholder>\.{4,}[ \t]*\.{4,}))"
    )
    REFERENCE_PATTERN = re.compile(r"Pos\.?\s*(\d{2,4})\.(\d{1,4})(?:\s*-\s*(\d{1,4}))?")

    def parse(self, text: str) -> list[Position]:
        self._positions: dict[str, Position] = {}
        self._order: list[str] = []
        self._current_chapter: str | None = None
        self._active_group: str | None = None
        self._active_subgroup: str | None = None

        markers = list(self.MARKER_PATTERN.finditer(text))
        for index, marker in enumerate(markers):
            body = self._body_text(text, markers, index)
            self._process_marker(marker, body)

        return [self._positions[number] for number in self._order]

    @staticmethod
    def _body_text(text: str, markers: list[re.Match], index: int) -> str:
        start = markers[index].end()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        return text[start:end].strip()

    def _process_marker(self, marker: re.Match, body: str) -> None:
        title = self._first_line(body)
        if not self._looks_like_real_position(title):
            return

        number, level, parent_number = self._resolve_number_and_level(marker)
        if number is None:
            return

        if level == "group":
            self._active_group, self._active_subgroup = number, None
        elif level == "subgroup":
            self._active_subgroup = number

        if number in self._positions:
            # Fortsetzung nach Seitenumbruch -- Text anhaengen statt doppelten Knoten zu erzeugen
            self._positions[number].text += "\n\n" + body
            return

        is_eventual = "eventual" in body.lower()
        menge = einheit = einzelpreis = gesamtpreis = None
        if level == "leaf":
            menge, einheit, einzelpreis, gesamtpreis = self._extract_quantity(body)

        self._positions[number] = Position(
            number=number,
            level=level,
            title=title,
            text=body,
            parent_number=parent_number,
            is_custom=bool(marker.group("r")),
            is_eventual=is_eventual,
            refers_to=self._extract_references(body) if is_eventual else [],
            menge=menge,
            einheit=einheit,
            einzelpreis=einzelpreis,
            gesamtpreis=gesamtpreis,
        )
        self._order.append(number)

    def _resolve_number_and_level(self, marker: re.Match) -> tuple[str | None, str, str | None]:
        if marker.group("chapter"):
            number = marker.group("chapter")
            self._current_chapter = number
            self._active_group = self._active_subgroup = None
            return number, "chapter", None

        if marker.group("continuation"):
            number = marker.group("continuation")
            self._current_chapter = number.split(".")[0]
            suffix = number.split(".", 1)[1]
        else:
            if self._current_chapter is None:
                return None, "leaf", None  # Sub-Marker ohne vorherigen Kapitelkontext -- ueberspringen statt zu raten
            suffix = marker.group("sub")
            number = f"{self._current_chapter}.{suffix}"

        level = self._level_for_suffix(suffix)
        parent_number = self._active_subgroup or self._active_group or self._current_chapter
        return number, level, parent_number

    @staticmethod
    def _level_for_suffix(suffix: str) -> str:
        # NPK-Konvention: "x00" ist ein Grundtext fuer die ganze Hunderter-Gruppe, "xy0" nur fuer
        # die Zehner-Untergruppe, alles andere ist eine bepreiste Folge- oder Eventualposition.
        if suffix.endswith("00"):
            return "group"
        if suffix.endswith("0"):
            return "subgroup"
        return "leaf"

    @staticmethod
    def _first_line(body: str) -> str:
        return body.split("\n", 1)[0].strip() if body else ""

    def _looks_like_real_position(self, title: str) -> bool:
        if self.GANTT_NOISE_PATTERN.search(title):
            return False  # Bauablaufplan-Zeile, keine echte LV-Position
        if not re.search(r"[A-Za-zÄÖÜäöü]{2,}", title):
            return False  # Titel ohne echtes Wort (z.B. "%", "m3", ").") -- Fehltreffer aus einer Mengen-/Zahlenzeile
        return True

    def _extract_quantity(self, text: str) -> tuple[float | None, str | None, float | None, float | None]:
        # Bei mehreren Treffern im Textblock (z.B. Mengenangabe in einer Erklaerung, dann die
        # echte Mengenzeile am Ende der Position) ist der LETZTE Treffer zuverlaessig die echte
        # Mengenzeile.
        for match in reversed(list(self.QUANTITY_PATTERN.finditer(text))):
            qty = parse_swiss_number(match.group("qty"))
            unit = match.group("unit")
            if match.group("placeholder"):
                return qty, unit, None, None  # Angebot: Menge/Einheit aus der LV-Vorlage, Preis noch nicht ausgefuellt

            price = parse_swiss_number(match.group("price"))
            total = parse_swiss_number(match.group("total"))
            if match.group("open") or match.group("close"):
                total = -total  # Minderpreis steht in Klammern im Original
            if qty is not None and price is not None and total is not None and abs(qty * price - abs(total)) < 0.5:
                return qty, unit, price, total
        return None, None, None, None

    def _extract_references(self, text: str) -> list[str]:
        refs: list[str] = []
        for match in self.REFERENCE_PATTERN.finditer(text):
            chapter, start, end = match.group(1), match.group(2), match.group(3)
            refs.append(f"{chapter}.{start}")
            if end:
                refs.append(f"{chapter}.{end}")
        return refs


# ---------------------------------------------------------------------------
# WerkvertragParser
# ---------------------------------------------------------------------------


class WerkvertragParser:
    """Composes the section parsers above into a single `Werkvertrag`."""

    HEADER_WINDOW = 3000

    def __init__(self, text: str):
        self.text = text
        self.meta_parser = MetaParser()
        self.beteiligte_parser = BeteiligteParser()
        self.vertragsdetails_parser = VertragsdetailsParser()
        self.konditionen_parser = KonditionenParser()
        self.vorbedingungen_parser = VorbedingungenParser()
        self.position_parser = PositionParser()

    def parse(self) -> Werkvertrag:
        header = self.text[: self.HEADER_WINDOW]
        konditionen = self.konditionen_parser.parse(self.text)

        return Werkvertrag(
            kopf=self.meta_parser.parse(header),
            auftragssumme_brutto=konditionen.brutto,
            auftragssumme_netto=konditionen.netto,
            beteiligte=self.beteiligte_parser.parse(header),
            vertragsdetails=self.vertragsdetails_parser.parse(header),
            konditionen=konditionen,
            vorbedingungen=self.vorbedingungen_parser.parse(self.text),
            positionen=self.position_parser.parse(self.text),
        )
