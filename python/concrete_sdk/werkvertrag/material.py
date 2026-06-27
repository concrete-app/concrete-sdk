class MaterialClassifier:
    """Classifies positions one at a time, in document order, against the running set of
    materials it has already assigned earlier in the same contract.

    `llm` is a caller-supplied chat model; `llm.with_structured_output(MaterialClassification)` is
    called once in `__init__` to build the actual per-call model. One instance is good for exactly
    one document -- `known_materials` is per-contract state, not meant to be reused across calls
    to `enrich_materials`.
    """

    def __init__(self, llm):
        self.llm = llm
        self.known_materials: list[str] = []
        self.material_classification_prompt =  """\
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

    async def classify(self, text_to_classify: str) -> str:
            return await self.llm.ainvoke([
                {"role": "system", "content": self.material_classification_prompt},
                {"role": "user", "content": self.build_user_prompt(text_to_classify) },
            ])

    def build_user_prompt(self, text_to_classify: str) -> str:
        materials_block = (
            "Bisherige Materialien: " + ", ".join(self.known_materials)
            if self.known_materials
            else "Bisherige Materialien: (noch keine)"
        )
        return f"{materials_block}\n\nPosition {text_to_classify}"
