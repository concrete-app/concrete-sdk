"""LLM-based material classification for Werkvertrag/LV positions.

The deterministic parser (`parser.py`) never fills `Position.material` -- see the comment on
that field. This module is the LLM enrichment it's waiting for.
"""

import logging
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .parser import Position

log = logging.getLogger("concrete_sdk.werkvertrag.material")


class PositionMaterial(BaseModel):
    position_number: str = Field(..., description="Exakt die 'position_number' aus der Eingabe.")
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


class MaterialClassificationBatch(BaseModel):
    classifications: list[PositionMaterial] = Field(
        ..., description="Genau eine Klassifikation pro Position aus der Eingabe, in beliebiger Reihenfolge."
    )


class MaterialClassifier:
    """Classifies positions in sequential batches, against the running set of materials it has
    already assigned in earlier batches of the same contract.

    Batches (not individual positions) run sequentially: each batch's prompt depends on the
    accumulated `known_materials` from every earlier batch, which is what keeps "Gipskartonplatte"
    and "Gipsplatte 12.5mm Feuerschutz" from becoming two different labels for the same material
    across one contract. Within a batch, the model classifies all positions in one call -- it sees
    them all at once, so it can also dedupe a newly-introduced material across that batch itself.

    `llm` is a caller-supplied chat model; `llm.with_structured_output(MaterialClassificationBatch)`
    is called once in `__init__` to build the actual per-call model. One instance is good for
    exactly one document -- `known_materials` is per-contract state, not meant to be reused across
    documents.
    """

    BATCH_SIZE = 10

    MATERIAL_CLASSIFICATION_PROMPT = """\
Erkenne das konkrete Baumaterial (z.B. Gipsplatte, OSB, Mineralwolle, Beton, Stahl) in jeder der
folgenden LV-Positionen -- nicht die Arbeitsleistung oder Konstruktion. Klassifiziere JEDE Position
einzeln, auch wenn mehrere das gleiche Material nennen.

- Passt es zu einem Eintrag in "Bisherige Materialien" (auch bei Synonym/Abkürzung, z.B.
  "Gipskartonplatte" == "Gipsplatte")? -> action="existing", material=genau dieser Eintrag.
- Sonst, falls ein Material genannt wird -> action="new", material=kurzes normalisiertes Label
  (Produktgattung statt voller Beschreibung, z.B. "Gipsplatte" statt "Gipsplatte 12.5mm F30 weiss").
  Nennen mehrere Positionen in diesem Batch dasselbe neue Material, gib ihnen dasselbe Label.
- Kein Material erkennbar (Montage, Transport, Regie) -> action="none".

Antworte mit genau einer Klassifikation pro Position, position_number exakt wie angegeben.
"""

    def __init__(self, llm, positions: list[Position]):
        self.model = llm.with_structured_output(MaterialClassificationBatch)
        self.positions = positions
        self.known_materials: list[str] = []

    def _build_user_prompt(self, batch: list[Position]) -> str:
        materials_block = (
            "Bisherige Materialien: " + ", ".join(self.known_materials)
            if self.known_materials
            else "Bisherige Materialien: (noch keine)"
        )
        positions_block = "\n\n".join(
            f"Position {position.number}: {position.title}\n{position.text}" for position in batch
        )
        return f"{materials_block}\n\n{positions_block}"

    async def _classify_batch(self, batch: list[Position]) -> MaterialClassificationBatch:
        try:
            return await self.model.ainvoke([
                {"role": "system", "content": self.MATERIAL_CLASSIFICATION_PROMPT},
                {"role": "user", "content": self._build_user_prompt(batch)},
            ])
        except Exception:
            # A failed batch must not abort enrichment for the rest of the document -- degrade
            # this batch to "no classifications" and let the loop continue with the next one.
            log.exception(
                "[material] classification failed for batch %s",
                [position.number for position in batch],
            )
            return MaterialClassificationBatch(classifications=[])

    async def classify_positions(self) -> list[Position]:
        """Classifies every position in document order, mutating `position.material` in place
        and returning the same list for convenience."""
        positions_to_classify = [position for position in self.positions if position.text.strip()]

        for start in range(0, len(positions_to_classify), self.BATCH_SIZE):
            batch = positions_to_classify[start : start + self.BATCH_SIZE]
            batch_by_number = {position.number: position for position in batch}

            result = await self._classify_batch(batch)
            for classification in result.classifications:
                position = batch_by_number.get(classification.position_number)
                if position is None or classification.action == "none" or not classification.material:
                    continue

                # Pydantic can't constrain action="existing" to actually name a list member -- if
                # the model hallucinates a near-miss label, treat it as new rather than silently
                # dropping it, which would otherwise lose the material entirely.
                position.material = classification.material
                if classification.material not in self.known_materials:
                    self.known_materials.append(classification.material)

        return self.positions
