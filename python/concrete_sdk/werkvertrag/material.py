"""LLM-based material classification for Werkvertrag/LV positions.

The deterministic parser (`parser.py`) never fills `Position.material` -- see the comment on
that field. This module is the LLM enrichment it's waiting for.
"""

import logging
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .parser import Position

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


class MaterialClassifier:
    """Classifies positions one at a time, in document order, against the running set of
    materials it has already assigned earlier in the same contract. This has to be sequential
    rather than parallel/batched: each call's prompt depends on the accumulated output of every
    earlier call, which is what keeps "Gipskartonplatte" and "Gipsplatte 12.5mm Feuerschutz" from
    becoming two different labels for the same material across one contract.

    `llm` is a caller-supplied chat model; `llm.with_structured_output(MaterialClassification)` is
    called once in `__init__` to build the actual per-call model. One instance is good for exactly
    one document -- `known_materials` is per-contract state, not meant to be reused across documents.
    """

    MATERIAL_CLASSIFICATION_PROMPT = """\
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

    def __init__(self, llm, positions: list[Position]):
        self.model = llm.with_structured_output(MaterialClassification)
        self.positions = positions
        self.known_materials: list[str] = []

    def _build_user_prompt(self, position: Position) -> str:
        materials_block = (
            "Bisherige Materialien: " + ", ".join(self.known_materials)
            if self.known_materials
            else "Bisherige Materialien: (noch keine)"
        )
        return f"{materials_block}\n\nPosition {position.title}\n\n{position.text}"

    async def _classify_position(self, position: Position) -> MaterialClassification:
        try:
            return await self.model.ainvoke([
                {"role": "system", "content": self.MATERIAL_CLASSIFICATION_PROMPT},
                {"role": "user", "content": self._build_user_prompt(position)},
            ])
        except Exception:
            # A single failed position must not abort enrichment for the other ~99 -- degrade to
            # "none" and let the loop continue.
            log.exception("[material] classification failed for position %s", position.number)
            return MaterialClassification(action="none", material=None)

    async def classify_positions(self) -> list[Position]:
        """Classifies every position in document order, mutating `position.material` in place
        and returning the same list for convenience."""
        for position in self.positions:
            if not position.text.strip():
                continue

            result = await self._classify_position(position)
            if result.action == "none" or not result.material:
                continue

            # Pydantic can't constrain action="existing" to actually name a list member -- if the
            # model hallucinates a near-miss label, treat it as new rather than silently dropping
            # it, which would otherwise lose the material entirely.
            position.material = result.material
            if result.material not in self.known_materials:
                self.known_materials.append(result.material)

        return self.positions
