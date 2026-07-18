"""Grobkategorie (coarse category) classification for Werkvertrag/LV positions.

Deterministic, alias/regex-based -- no LLM, unlike the LLM-based `MaterialClassifier` this module
replaces (see git history of the deleted `material.py`). Ported from a companion research project
(`wv-parser`) that validated this approach at 100% classification accuracy against a hand-corrected
ground truth; see that project's `grobkategorie.py` module docstring for the full derivation
history of `GROBKATEGORIE_ALIASES` below and the day-by-day fixes that got it there.

Multi-label: `classify_grobkategorie` returns every category tied for the MOST matching aliases in
a position's text (a list, possibly empty) -- not a single winner, since a position can genuinely
belong to more than one Grobkategorie at once (e.g. a colour surcharge on an Akustikplatten item is
both Baumaterial and Malerarbeiten). Scoring by hit count, not just "first category with any
match", matters in practice: a text genuinely about one category tends to hit several of that
category's aliases, while an incidental cross-reference into another category's vocabulary usually
hits just one. A tie is only trusted once every tied category clears `_MIN_HITS_FOR_GENUINE_TIE`
hits -- below that, it's usually two unrelated incidental single-word collisions on generic/
administrative text, not evidence the text is genuinely about both, and collapses back to a single
winner (`GROBKATEGORIE_ALIASES`'s definition order).

`GROBKATEGORIE_ALIASES` below is a frozen snapshot, not re-derived at runtime. The source project
derives it by tokenizing one hand-labeled Werkvertrag's ground truth and keeping every word
exclusive to a single category -- a reasonable one-time bootstrap for a vocabulary list, but not
something a production library should recompute from (or ship) a single evaluation document's data
file. If classification quality needs improving for a document type these aliases don't cover well,
extend this dict directly rather than reintroducing a ground-truth-driven derivation pipeline here.

Deliberately dropped relative to the source project: page-based narrowing
(`GROBKATEGORIE_PAGE_SETS` and the `pages` argument on `classify_grobkategorie`). Those page sets
record which physical pages each category appeared on in one specific PDF -- meaningless, and
actively misleading, for any other Werkvertrag.
"""

from __future__ import annotations

import re

from .parser import Position

GROBKATEGORIE_ALIASES: dict[str, list[str]] = {
    "Leimholz": [
        "duo", "triobalken", "leimholz", "brettschichtholz", "druckgurt", "einbinder", "randrippen",
    ],
    "Verbindungsmittel": [
        "Rillennägel", "SDü/PB", "Hilti-HSA", "ANCRA", "Befestigungsmittel",
    ],
    "Stahlteile": [
        "Stahlblech", "Schlitzblech", "Grundplatte", "Anschlussblech", "Kopfplatte", "Kehlnaht",
        "Zugstange", "Zugstab",
    ],
    "Daemmung": [
        "mineralfaserplatten", "schmelzpunkt", "bindemittel", "rohdichte", "formaldehydfreie",
        "dissco", "flumroc", "Dämmung", "Schalldämmung", "Wärmedämmung",
    ],
    "Baumaterial": [
        "osb", "magnesitgebundener", "befestigt", "balken", "naturton", "holzwolle", "fine",
        "schattenfugen", "akustikplatten", "schallabsorbtionsklasse", "gefast", "längsstösse",
        "heradesign", "brandverhaltensklasse", "dreischichtplatten", "gkb", "gipskartonbauplatten",
        "anwendung", "laubengang", "spanplatten", "duripanel", "zementgebundenen", "fassadenbahn",
        "kunststoffbahn", "noniusabhänger", "abhängehöhe", "direktschwingabhänger",
    ],
    "Fassadenschalung": [
        "schalung", "oberflächenbehandlung", "einheitlich", "gerundet", "profil", "rift", "kamm",
        "holzfeuchte", "vertikale", "halbrift", "nut", "massivholzschalung", "rostfreiem",
        "schweizerholz", "fassadenbekleidung", "deckbrett", "sturzbekleidung", "leibung",
        "silverwood", "allseitiger", "sichtseitiger", "holzoberflächen", "dreiseitiger",
    ],
    "Malerarbeiten": [
        "zwischenschliff", "innenbereich", "jetfinish", "vsh", "suncare", "weisslicher",
        "schweizerischer", "hobelwerke", "zertifikat", "verbandes", "stationsstrasse", "bern",
        "geschliffen", "lack", "lieferant", "farbenfarbrik", "böhme", "liebefeld",
        "farbpigmentierung", "finish", "lasur", "lasureinstellungen", "baustelle", "jetmatt",
        "gespritzt", "schlussanstrich", "weissliche",
    ],
    "Gipserarbeiten": [
        "schicht", "spachtelungen", "oberflächengüte", "gipsplatten", "oberste", "qualitätsstufe",
    ],
    "Blechteile": [],
    "Lignatur": ["LIGNATUR", "Lignatur"],
    "Bodenrost": ["Bodenrost", "Bodenroste"],
    "Tragwerk": [],
}

# A small, fixed set of common German noun case/plural endings ("Verbindungsmittel" the alias vs.
# "Verbindungsmitteln" the actual text, dative plural) -- not general prefix matching, which would
# be dangerous for short aliases (a bare "Nut" must never match inside unrelated "Nutzlast"). Each
# ending is tried, still anchored by \b on both sides, so only a real inflected form of the alias
# itself matches.
_GERMAN_NOUN_ENDINGS = r"(?:e|en|er|es|n|s)?"
_ALIAS_CANDIDATES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b" + re.escape(alias.lower()) + _GERMAN_NOUN_ENDINGS + r"\b"), kategorie)
    for kategorie, aliases in GROBKATEGORIE_ALIASES.items()
    for alias in aliases
]

_HYPHEN_LINEWRAP_RE = re.compile(r"(\w)-\n(\w)")

# A tie only counts as genuine multi-label evidence once every tied category cleared this many
# alias hits -- below it, a tie is far more likely two incidental single-word collisions on
# generic/administrative text than the text actually being about both. Below the threshold,
# collapse back to a single winner (GROBKATEGORIE_ALIASES definition order).
_MIN_HITS_FOR_GENUINE_TIE = 2


def classify_grobkategorie(text: str) -> list[str]:
    """Returns every Grobkategorie tied for the most matching aliases in `text` (whole word,
    case-insensitive, tolerant of common German noun inflections -- see `_GERMAN_NOUN_ENDINGS`),
    or `[]` if nothing matched."""
    # The source transcription sometimes hard-wraps mid-word at a hyphen ("...zugehöriger Rillen-
    # \nnägel." for "Rillennägel") -- rejoin those before matching, or a real alias never lines up
    # with the text at all. Only a hyphen directly glued to a newline (no space) qualifies, so
    # genuine hyphenated phrases like "Mehr- oder Minderpreis" (hyphen-SPACE-word) are untouched.
    normalized = _HYPHEN_LINEWRAP_RE.sub(r"\1\2", text.lower())
    hit_counts: dict[str, int] = {}
    for pattern, kategorie in _ALIAS_CANDIDATES:
        if pattern.search(normalized):
            hit_counts[kategorie] = hit_counts.get(kategorie, 0) + 1
    if not hit_counts:
        return []
    max_hits = max(hit_counts.values())
    tied_at_max = [kategorie for kategorie in GROBKATEGORIE_ALIASES if hit_counts.get(kategorie, 0) == max_hits]
    if len(tied_at_max) > 1 and max_hits < _MIN_HITS_FOR_GENUINE_TIE:
        return [tied_at_max[0]]  # not enough evidence to call this a real tie, see _MIN_HITS_FOR_GENUINE_TIE
    return tied_at_max


_POS_REFERENCE_RE = re.compile(r"[Zz]u\s+Pos\.?\s*(\d{1,4}\.\d{1,4})")
_PRICE_ADJUSTMENT_RE = re.compile(r"^(?:Mehr|Minder)(?:preis|-)", re.IGNORECASE)


def _own_text(text: str) -> str:
    """The position's own newly-added text, as opposed to any group/subgroup header text
    `PositionParser` prepended to it (see `_with_inherited_context` in `parser.py`) -- inherited
    text and a leaf's own text are always joined with a blank line, so the last "\\n\\n"-separated
    segment is always the leaf's own."""
    return text.rsplit("\n\n", 1)[-1].strip()


def classify_positions(positions: list[Position]) -> list[Position]:
    """Classifies a whole document's (leaf) positions in one pass, mutating `position.grobkategorie`
    in place (mirroring the old `MaterialClassifier.classify_positions` convention) and returning
    the same list for convenience. Fully deterministic -- no `llm` argument. Pass only leaf
    positions (`level == "leaf"`) -- price-adjustment resolution and the reference-chain logic below
    only make sense between leaves.

    Beyond a position's own text, resolves what a position corrects or details on top of whatever
    `classify_grobkategorie` already found: a "Mehrpreis/Minderpreis für ..." price adjustment, or a
    supplementary detail like "Ausschnitt ... Zu Pos. NNN.NNN". Two fallbacks, tried in order:
      1. An explicit "zu Pos. NNN.NNN" cross-reference in the position's own text -- adopt that
         referenced position's result. The reference is named and unambiguous, so this is safe
         regardless of whether the position's own text already had alias hits of its own.
      2. No reference (or it didn't resolve to anything) -- for positions whose own text looks like
         a price adjustment specifically (starts with "Mehr-"/"Minder-"), adopt the nearest
         PRECEDING position in `positions`' own order that did resolve, since NPK price adjustments
         are always listed immediately after the item they adjust.
    Merged into (not just filling in for) the position's own per-text result, since a price
    adjustment line can genuinely carry its own category signal (generic paint/finish vocabulary
    reading as Malerarbeiten) *and* inherit the referenced item's (e.g. Baumaterial) at once.
    `positions` must already be in the document's original order for (2) to be meaningful.
    """
    results: dict[str, list[str]] = {p.number: classify_grobkategorie(p.text) for p in positions}

    # An inline "zu Pos. NNN.NNN" cross-reference in the document's own running text never carries
    # the "R" customized-position marker (that's a transcription/markup convention on the position's
    # OWN listing, not part of how that position gets referred to elsewhere) -- so the bare suffix
    # used for lookup here has to strip any leading "R" from each component too, or a reference to
    # e.g. "452.491" never finds the real position stored as "...452.R491".
    numbers_by_bare_suffix: dict[str, list[str]] = {}
    for number in results:
        bare = [re.sub(r"^R", "", part) for part in number.split(".")[-2:]]
        numbers_by_bare_suffix.setdefault(".".join(bare), []).append(number)

    last_resolved: str | None = None
    for p in positions:
        number = p.number
        own_text = _own_text(p.text)

        resolved: list[str] = []
        ref_match = _POS_REFERENCE_RE.search(own_text)
        if ref_match:
            candidates = numbers_by_bare_suffix.get(ref_match.group(1), [])
            resolved = next((results[c] for c in candidates if results[c]), [])
        if not resolved and _PRICE_ADJUSTMENT_RE.match(own_text) and last_resolved not in (None, number):
            resolved = results[last_resolved]
        if resolved:
            extra = [c for c in resolved if c not in results[number]]
            if extra:
                results[number] = results[number] + extra
        if results[number]:
            last_resolved = number  # lets a chain of consecutive adjustment lines propagate

    for p in positions:
        p.grobkategorie = results[p.number]
    return positions
