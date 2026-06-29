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


_LEADING_DIGITS = re.compile(r"\d{1,4}")


def _is_wrapped_continuation(line: str) -> bool:
    # A real bare chapter marker ("100 Vorarbeiten.") always has whitespace right after its
    # digits, and a real NPK continuation number ("211.111 ...") always has "." + digit right
    # after. Anything else immediately glued to the digits ("27/ca.700mm.", "15kN/m1.",
    # "700ff enthalten.", "265:2012", "15%") is a value that got hard-wrapped onto its own line
    # by the LLM transcription step and would otherwise be misread by MARKER_PATTERN below as a
    # new chapter.
    #
    # Deliberately NOT a single regex: `\d{1,4}\S` looks equivalent but isn't -- `\S` matches
    # digits too, so the engine backtracks `\d{1,4}` down to fewer digits and lets `\S` consume
    # one of the "leftover" digits, silently matching genuine chapters like "100 Vorarbeiten."
    # as if the unit-glue case had fired. Plain indexing has no such backtracking pitfall.
    match = _LEADING_DIGITS.match(line)
    if not match:
        return False
    rest = line[match.end():]
    if not rest or rest[0].isspace():
        return False
    if rest[0] == "." and len(rest) > 1 and rest[1].isdigit():
        return False
    return True


_FOOTER_LETTERHEAD = re.compile(r"CH[EF]-\d{3}\.\d{3}\.\d{3}\s*MWST")  # OCR sometimes confuses E/F
_FOOTER_PROJEKT = re.compile(r"^Projekt:\s*\d+\s*$")
_FOOTER_SEITE = re.compile(r"^Seite:\s*\d+\s*$")
_FOOTER_BKP = re.compile(r"^BKP:\s*\d+\s*$")
_FOOTER_AUFTRAG = re.compile(r"^Auftrag:\s*\d*\s*NPK-Bau:\s*\d+.*$")
_DATE_LINE = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{4}\s*$")
_CATALOG_ID = re.compile(r"NPK-Bau:\s*(\d+)")
# A single Werkvertrag can concatenate several independent NPK catalogs back to back (e.g. "343
# Hinterlueftete Fassadenbekleidungen" followed by "931 Holzbauarbeiten"), each restarting its own
# chapter numbering from "000". The "Auftrag: N NPK-Bau: NNN <name> ..." line is the only marker of
# where one catalog ends and the next begins, so instead of discarding it as pure noise like the
# rest of the footer, it's rewritten into this sentinel so PositionParser can pick the boundary
# back up after normalize_markdown runs and namespace position numbers per catalog.
_CATALOG_SENTINEL_PREFIX = "\x00CATALOG:"
_CATALOG_SENTINEL_SUFFIX = "\x00"
_BOLD_WRAPPED_LINE = re.compile(r"^\*\*(.+)\*\*$")


def _strip_footer_noise(text: str) -> str:
    # Every page break re-injects the contractor's letterhead plus a handful of fixed-shape
    # boilerplate lines into the markdown, splitting position text that spans the break. The
    # letterhead line is always identifiable by the Swiss UID/MWST suffix regardless of which
    # company it is, and "Projekt: NNNN" / "Seite: NNN" are always immediately followed (no blank
    # line) by one further noise line -- the client name/city, and the page date -- so those can
    # be dropped positionally without needing to know what they say. The one thing this can't
    # catch generically is the repeated project-site-address line (e.g. "Industriestrasse G11,
    # Luzern"), since recognizing it would require comparing against the address already parsed
    # out of the document header; left as a known residual, same as the few unresolved soft-wrap
    # cases in _is_wrapped_continuation.
    kept: list[str] = []
    skip_next = False
    for line in text.split("\n"):
        stripped = line.strip()
        if skip_next:
            skip_next = False
            continue
        if _FOOTER_LETTERHEAD.search(stripped):
            continue
        if _FOOTER_PROJEKT.match(stripped):
            skip_next = True
            continue
        if _FOOTER_SEITE.match(stripped):
            skip_next = True
            continue
        if _FOOTER_AUFTRAG.match(stripped):
            catalog_id = _CATALOG_ID.search(stripped)
            if catalog_id:
                kept.append(f"{_CATALOG_SENTINEL_PREFIX}{catalog_id.group(1)}{_CATALOG_SENTINEL_SUFFIX}")
            continue
        if _FOOTER_BKP.match(stripped) or _DATE_LINE.match(stripped):
            continue
        kept.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept))


def _unwrap_bold_headings(text: str) -> str:
    # The LLM sometimes renders a genuine chapter/group heading as a markdown-bold line
    # ("**000 Bedingungen**"), which MARKER_PATTERN's start-of-line anchor then never even
    # attempts to match -- silently dropping that chapter. Restricted to fully bold-wrapped,
    # single-line, non-table rows: a price-summary table row that happens to start with a bold
    # cell ("**214 Montagebau in Holz** | **3'301'102.15** | ...") has the exact same shape at the
    # start of the line, but unwrapping it would misread an unrelated summary row as a real
    # chapter marker and corrupt whatever legitimately owns that chapter number.
    unwrapped: list[str] = []
    for line in text.split("\n"):
        if "|" not in line:
            match = _BOLD_WRAPPED_LINE.match(line)
            if match:
                line = match.group(1)
        unwrapped.append(line)
    return "\n".join(unwrapped)


def normalize_markdown(text: str) -> str:
    """Strips recurring page-footer boilerplate, unwraps bold-only heading lines, then rejoins
    wrapped-value lines that would otherwise be misread as bogus chapter markers.

    Scoped narrowly to those failure modes -- it does not attempt general PDF-text de-wrapping
    (e.g. a label like "Architekt:" with its value on the next line is left untouched, since
    MetaParser/BeteiligteParser rely on that line break). Known residual cases this doesn't catch:
    a wrap that lands after the digits *and* a space (e.g. "...Art.\\n22 + 23 ...", where "Art."
    is an abbreviation, not a real sentence end) is indistinguishable from a genuine chapter
    header by shape alone; and the repeated project-site-address footer line (see
    `_strip_footer_noise`) isn't identifiable without the document's own parsed address.
    """
    text = _strip_footer_noise(text)
    text = _unwrap_bold_headings(text)
    normalized: list[str] = []
    for line in text.split("\n"):
        if normalized and _is_wrapped_continuation(line):
            normalized[-1] = f"{normalized[-1]} {line}".rstrip()
        else:
            normalized.append(line)
    return "\n".join(normalized)


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
    CATALOG_PATTERN = re.compile(
        re.escape(_CATALOG_SENTINEL_PREFIX) + r"(?P<id>\d+)" + re.escape(_CATALOG_SENTINEL_SUFFIX)
    )

    def parse(self, text: str) -> list[Position]:
        self._positions: dict[str, Position] = {}
        self._order: list[str] = []
        self._current_chapter: str | None = None
        self._max_group_suffix: int | None = None  # hoechster ".x00"-Suffix im aktuellen Kapitel
        self._current_catalog: str | None = None

        text = normalize_markdown(text)

        # A document with only one NPK catalog (the common case) keeps its existing bare numbering
        # untouched -- only once a second, independently-numbered catalog is actually detected do
        # position numbers get namespaced by catalog id, see _qualify().
        catalog_events = list(self.CATALOG_PATTERN.finditer(text))
        self._multi_catalog = len({event.group("id") for event in catalog_events}) > 1

        events = sorted(catalog_events + list(self.MARKER_PATTERN.finditer(text)), key=lambda m: m.start())
        for index, event in enumerate(events):
            if event.re is self.CATALOG_PATTERN:
                self._current_catalog = event.group("id")
                continue
            start = event.end()
            end = events[index + 1].start() if index + 1 < len(events) else len(text)
            body = text[start:end].strip()
            self._process_marker(event, body)

        return [self._positions[number] for number in self._order]

    def _qualify(self, chapter: str) -> str:
        if self._multi_catalog and self._current_catalog:
            return f"{self._current_catalog}.{chapter}"
        return chapter

    def _process_marker(self, marker: re.Match, body: str) -> None:
        title = self._first_line(body)
        if not self._looks_like_real_position(title):
            return

        number, level, parent_number = self._resolve_number_and_level(marker)
        if number is None:
            return

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
            chapter = marker.group("chapter")
            self._set_chapter(chapter)
            return self._qualify(chapter), "chapter", None

        if marker.group("continuation"):
            # Vollqualifizierte Nummer steht explizit im Text (typischerweise nach einem
            # Seitenumbruch) -- vertrauenswuerdig, kein Kapitelwechsel-Rateversuch noetig.
            number = marker.group("continuation")
            chapter, suffix = number.split(".", 1)
            if chapter != self._current_chapter:
                self._set_chapter(chapter)
        else:
            if self._current_chapter is None:
                return None, "leaf", None  # Sub-Marker ohne vorherigen Kapitelkontext -- ueberspringen statt zu raten
            suffix = marker.group("sub")

            # NPK-Gruppen ("x00") zaehlen innerhalb eines Kapitels nur aufwaerts (.100 -> .200 ->
            # ... -> .800), nie zurueck. Faellt ein bloss angehaengter (nicht vollqualifizierter)
            # Gruppen-Marker auf einen bereits gesehenen oder kleineren Hunderter-Block zurueck, ist
            # so gut wie sicher das eigentliche Kapitel-Header (z.B. das NPK-Standardpaar "012
            # Inbegriffene" -> "013 Nicht inbegriffene Leistungen") bei der Transkription verloren
            # gegangen -- ohne diese Korrektur wuerde der gesamte Block sonst stillschweigend ins
            # vorherige Kapitel einsortiert (und bei Nummern-Kollision sogar in dessen Text gemerged).
            if self._level_for_suffix(suffix) == "group" and self._max_group_suffix is not None:
                if int(suffix) <= self._max_group_suffix:
                    self._set_chapter(self._next_chapter_guess())

        level = self._level_for_suffix(suffix)
        if level == "group":
            self._max_group_suffix = max(self._max_group_suffix or 0, int(suffix))

        qualified_chapter = self._qualify(self._current_chapter)
        number = f"{qualified_chapter}.{suffix}"
        parent_number = self._structural_parent(qualified_chapter, suffix, level)
        return number, level, parent_number

    def _set_chapter(self, chapter: str) -> None:
        self._current_chapter = chapter
        self._max_group_suffix = None

    def _next_chapter_guess(self) -> str:
        # Bestmoegliche Annahme, wenn ein Kapitel-Header fehlt: das naechste Kapitel im NPK ist so
        # gut wie immer die fortlaufende Nummer (z.B. 012 -> 013) -- nicht beweisbar richtig, aber
        # zuverlaessiger als blind im falschen Kapitel weiterzulaufen.
        assert self._current_chapter is not None
        return str(int(self._current_chapter) + 1).zfill(len(self._current_chapter))

    @staticmethod
    def _level_for_suffix(suffix: str) -> str:
        # NPK-Konvention: "x00" ist ein Grundtext fuer die ganze Hunderter-Gruppe, "xy0" nur fuer
        # die Zehner-Untergruppe, alles andere ist eine bepreiste Folge- oder Eventualposition.
        if suffix.endswith("00"):
            return "group"
        if suffix.endswith("0"):
            return "subgroup"
        return "leaf"

    def _structural_parent(self, chapter: str, suffix: str, level: str) -> str | None:
        # Der NPK-Hierarchie liegt reine Ziffern-Arithmetik zugrunde (Hunderter = Gruppe, Zehner =
        # Untergruppe), nicht die Reihenfolge, in der Marker im Text auftauchen -- der Elternknoten
        # einer Position laesst sich daher direkt aus ihrer eigenen Nummer berechnen, ganz ohne
        # mutable "zuletzt gesehen"-Zeiger, die durch Geschwister-Positionen ueberschrieben wuerden.
        #
        # Existenz wird auf jeder Ebene geprueft, inkl. des Kapitels selbst: Tritt ein Kapitel nie
        # als eigene Marker-Zeile auf (nur als Praefix einer vollqualifizierten Nummer), waere
        # "chapter" sonst eine Referenz auf einen nie erzeugten Knoten -- lieber gar kein
        # parent_number als eine haengende Referenz, an der die Position im UI-Baum verschwindet.
        if level == "subgroup" and len(suffix) >= 3:
            group_number = f"{chapter}.{suffix[:-2]}00"
            if group_number in self._positions:
                return group_number
        if level == "leaf":
            if len(suffix) >= 2:
                subgroup_number = f"{chapter}.{suffix[:-1]}0"
                if subgroup_number in self._positions:
                    return subgroup_number
            if len(suffix) >= 3:
                group_number = f"{chapter}.{suffix[:-2]}00"
                if group_number in self._positions:
                    return group_number
        return chapter if chapter in self._positions else None

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
