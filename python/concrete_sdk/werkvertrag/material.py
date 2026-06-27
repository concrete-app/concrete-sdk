"""LLM-based material classification for Werkvertrag/LV positions.

The deterministic parser (`parser.py`) never fills `LvPosition.material` -- see the comment on
that field. This module is the LLM enrichment it's waiting for: it walks the parsed positions in
document order and asks the model, one position at a time, to either reuse a material label
already assigned earlier in the same contract, mint a new one, or assign none. This has to be
sequential rather than parallel/batched: each call's prompt depends on the accumulated output of
every earlier call, which is what keeps "Gipskartonplatte" and "Gipsplatte 12.5mm Feuerschutz" from
becoming two different labels for the same material across one contract.

Like `transcribe.py`, the LLM is a caller-supplied parameter -- pass any `langchain`-style chat
model (anything with `.with_structured_output(...)`); this module doesn't construct one itself.
"""

import logging
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .parser import LvPosition, WerkvertragParser

log = logging.getLogger("concrete_sdk.werkvertrag.material")


class MaterialClassification(BaseModel):
    action: Literal["existing", "new", "none"] = Field(
        ...,
        description=(
            "'existing' wenn die Position eines der bereits vergebenen Materialien aus der Liste "
            "nennt -- dann MUSS material exakt einem Eintrag der Liste entsprechen. "
            "'new' wenn ein Material genannt wird, das noch in keinem Eintrag der Liste vorkommt. "
            "'none' wenn der Text kein Material nennt (z.B. reine Arbeitsleistung, Montage, Transport)."
        ),
    )
    material: Optional[str] = Field(
        None,
        description=(
            "Bei action='existing': exakt eines der Labels aus 'Bisherige Materialien' (Zeichen für "
            "Zeichen identisch). Bei action='new': ein kurzes, normalisiertes Materiallabel "
            "(z.B. 'Gipsplatte', 'Grobspanplatte OSB', 'Mineralwolle'). Bei action='none': null."
        ),
    )


MATERIAL_SYSTEM_PROMPT = """\
Du klassifizierst Materialien in einer einzelnen Position eines Schweizer Leistungsverzeichnisses (LV).

Aufgabe: Prüfe den Positionstext auf ein genanntes Baumaterial (z.B. Gipsplatte, OSB-Platte,
Mineralwolle, Beton, Stahl). Es geht NICHT um die Arbeitsleistung oder Konstruktion, sondern um
das konkrete Material/Produkt.

Wenn ein Material genannt wird:
- Prüfe zuerst, ob es inhaltlich einem der "Bisherige Materialien" entspricht (auch bei
  abweichender Schreibweise, Abkürzung oder Synonym, z.B. "Gipskartonplatte" == "Gipsplatte",
  "OSB" == "Grobspanplatte OSB") -- falls ja: action="existing", material=genau dieses bestehende Label.
- Nur wenn kein bestehendes Label passt: action="new" mit einem neuen, kurzen, normalisierten Label
  (Produktgattung, nicht die volle Beschreibung -- z.B. "Gipsplatte" statt "Gipsplatte 12.5mm
  Feuerschutz F30 weiss").
- Wenn kein Material erkennbar ist (z.B. reine Montage-/Arbeitsposition, Transport, Regie): action="none".

Antworte ausschliesslich mit dem JSON-Objekt, kein Kommentar.
"""


def _build_user_prompt(position: LvPosition, known_materials: list[str]) -> str:
    materials_block = (
        "Bisherige Materialien: " + ", ".join(known_materials)
        if known_materials
        else "Bisherige Materialien: (noch keine)"
    )
    return f"{materials_block}\n\nPosition {position.number}: {position.title}\n\n{position.description}"


async def _classify_position(model, position: LvPosition, known_materials: list[str]) -> MaterialClassification:
    try:
        return await model.ainvoke([
            {"role": "system", "content": MATERIAL_SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(position, known_materials)},
        ])
    except Exception:
        # A single failed position must not abort enrichment for the other ~99 -- degrade to
        # "none" and let the loop continue.
        log.exception("[werkvertrag_material] classification failed for position %s", position.number)
        return MaterialClassification(action="none", material=None)


async def enrich_materials(extraction: WerkvertragParser, llm) -> None:
    """Classifies the material of every position in document order, mutating
    `extraction.positions[*].material` in place. Must run after `WerkvertragParser(full_text)` has
    built the position tree.

    `llm` is a caller-supplied chat model; `llm.with_structured_output(MaterialClassification)` is
    called once here to build the actual per-call model.
    """
    model = llm.with_structured_output(MaterialClassification)
    known_materials: list[str] = []
    for position in extraction.positions.values():
        if not position.description.strip():
            continue

        result = await _classify_position(model, position, known_materials)
        if result.action == "none" or not result.material:
            continue

        # Pydantic can't constrain action="existing" to actually name a list member -- if the
        # model hallucinates a near-miss label, treat it as new rather than silently dropping it,
        # which would otherwise lose the material entirely.
        position.material = result.material
        if result.material not in known_materials:
            known_materials.append(result.material)
