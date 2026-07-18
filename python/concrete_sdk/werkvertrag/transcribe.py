from langchain_core.language_models.chat_models import BaseChatModel
import asyncio
from pypdf import PdfReader, PdfWriter
from io import BytesIO
from pathlib import Path
import base64


# Safety net for character substitutions observed from the model on certain table layouts
# (e.g. Gantt/schedule tables) -- the source PDF's own text layer has correct umlauts, but the
# model's transcription of these two characters comes back wrong on some pages. Neither "‰" nor
# "¸" has any legitimate use in this document, so a blanket replace is safe.
CHARACTER_CORRUPTIONS = {
    "‰": "ä",
    "¸": "ü",
}


def clean_transcription(text: str) -> str:
    for bad, good in CHARACTER_CORRUPTIONS.items():
        text = text.replace(bad, good)
    return text


class PDFTranscriber:
    def __init__(self, pdf_path: str, llm: BaseChatModel):
        self.semaphore = asyncio.Semaphore(10)
        self.transcription = ""
        self.page_transcriptions: list[str] = []
        self.pdf_path = pdf_path
        self.llm = llm
        self.pages = self.split_pdf_into_pages(self.pdf_path)
        self.transcribe_system_prompt = """\
        Du transkribierst EINE EINZELNE SEITE eines PDF-Dokuments woertlich und vollstaendig als Markdown-Text.

        Regeln:
        - Gib JEDEN Textinhalt dieser Seite wieder, in Lesereihenfolge, ohne etwas auszulassen oder
        zusammenzufassen.
        - Diese Seite kann der Anfang, die Mitte oder das Ende einer mehrseitigen Tabelle sein. Transkribiere
        genau das, was auf DIESER Seite sichtbar ist -- auch wenn eine Tabelle ohne Kopfzeile beginnt (weil
        sie von der vorigen Seite fortgesetzt wird) oder mitten in einer Zeile endet. Erfinde keine
        Kopfzeile und schliesse keine Zeile ab, die auf der Seite nicht zu Ende ist.
        - NUR echte mehrspaltige Datentabellen mit klar erkennbaren Spaltenkoepfen (z.B. Konditionen-Tabelle
        mit Label/Prozent/Betrag, oder Auflistung-ABL-Tabelle mit Gebaeude/Position/Text/Betrag) als
        Markdown-Pipe-Tabelle wiedergeben (| Spalte | Spalte |) -- mit GENAU so vielen Spalten wie
        Spaltenkoepfen vorhanden sind, nicht mehr.
        - Alles andere (Deckblatt, Adressblocke, Unterschriftenfelder, Fliesstext, unklare Layouts, das
        Leistungsverzeichnis mit Positionsnummern) als normalen Text wiedergeben, NIEMALS als Tabelle
        erraten oder ein Tabellenraster erfinden.
        - Sobald eine Tabelle auf dieser Seite zu Ende ist, sofort mit dem naechsten Textabschnitt
        fortfahren. Eine Tabellenzeile niemals wiederholen oder eine leere Zeile anhaengen.
        - Im Leistungsverzeichnis steht am linken Rand vor manchen Positionsnummern ein einzelner Buchstabe
        "R" (Kennzeichnung fuer individuell angepasste Positionen, die vom Standard-NPK abweichen). Gib
        dieses "R" exakt wieder, wo es im Original steht -- nicht weglassen, nicht hinzufuegen.
        - Im Leistungsverzeichnis stehen zwei Arten von Nummern: ganze Kapitelnummern ohne Punkt (z.B. "919")
        und Unterpositionsnummern MIT einem Punkt direkt davor (z.B. ".110", ".111"). Dieser Punkt ist oft
        klein und leicht zu uebersehen, aber semantisch entscheidend -- gib ihn IMMER wieder, wenn er im
        Original vor der Zahl steht, auch wenn er kaum sichtbar ist.
        - Diese Seite kann gescannt sein. Lies den sichtbaren Bildinhalt genau, auch bei schlechter
        Bildqualitaet oder Schraeglage. Markiere wirklich unleserliche Stellen mit [unleserlich] statt
        etwas zu erfinden.
        - Keine Zusammenfassung, kein Kommentar, keine Code-Fences. Gib NUR den transkribierten Text dieser
        Seite zurueck.
        """

    def split_pdf_into_pages(self, pdf_path: str) -> list[bytes]:
        """
        Splits a PDF file into individual pages.
        Args:
            pdf_path (str): The path to the PDF file.
        Returns:
            list[bytes]: A list of bytes, each representing a page of the PDF.
        """

        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

        reader = PdfReader(BytesIO(pdf_bytes))
        pages = []
        for page in reader.pages:
            output = BytesIO()
            writer = PdfWriter()
            writer.add_page(page)
            writer.write(output)
            pages.append(output.getvalue())
        return pages

    async def transcribe_page(self, page_bytes: bytes) -> str:
        b64 = base64.b64encode(page_bytes).decode("ascii")
        msg = await self.llm.ainvoke(
            [
                {"role": "system", "content": self.transcribe_system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "media", "mime_type": "application/pdf", "data": b64},
                    ],
                },
            ]
        )
        content = msg.content
        if isinstance(content, list):
            content = "".join(
                block["text"] if isinstance(block, dict) else block
                for block in content
            )
        return clean_transcription(content)

    async def transcribe(self) -> str:
        """
        Transcribes the text from a PDF file, one page at a time. Keeps each page's own result
        around in `self.page_transcriptions` (not just the joined `self.transcription`) so callers
        that need per-position page tracking can build tagged input via
        `concrete_sdk.werkvertrag.parser.join_pages(self.page_transcriptions)` instead of a plain
        joined string.
        Returns:
            str: The transcribed text from the PDF (all pages joined).
        """
        async def _limited(page_bytes: bytes) -> str:
            async with self.semaphore:
                return await self.transcribe_page(page_bytes)

        self.page_transcriptions = await asyncio.gather(*[_limited(page) for page in self.pages])
        self.transcription = "\n".join(self.page_transcriptions)
        return self.transcription

    def export_to_markdown(self, output_path: str) -> None:
        """
        Writes the transcribed text to a markdown file.
        Args:
            output_path (str): Where to write the .md file.
        """
        Path(output_path).write_text(self.transcription, encoding="utf-8")
