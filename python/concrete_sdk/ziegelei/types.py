from dataclasses import dataclass
from datetime import date
from typing import Literal, Annotated

@dataclass
class Backstein:
    bezeichnung: str
    zusatz_kuerzel: str
    hoehe: int
    breite: int
    nut_und_kamm: bool
    def generate_text(self) -> str:
        return f"{self.bezeichnung} {self.zusatz_kuerzel} ({self.hoehe}/{self.breite}){'N+K' if self.nut_und_kamm else ''}"

@dataclass
class Tonsturz:
    breite: Annotated[int, "Breite des Tonsturzes in cm"]
    hoehe: Annotated[int, "Höhe des Tonsturzes in cm"]
    laenge: Annotated[int, "Länge des Tonsturzes in m"]
    verfuegbar: Annotated[bool, "Gibt an, ob der Tonsturz verfügbar ist oder nicht"]


@dataclass
class Bestellung:
    firma: str
    baustelle_strasse: str
    baustelle_plz: str
    lieferdatum: date
    franko_bau_oder_abgeholt: bool
    zufahrt: Literal[
        "Solo-Fahrzeug (3-Achser) ca. 17 Paletten",
        "Zufahrt mit Anhänderzug ca. 29 Paletten",
        "Ablad mit Kranwagen (4 Paletten weniger)",
    ]
    liefer_richtzeiten: Literal[
        "07:00",
        "09:00 - 12:00",
        "Nachmittag"
    ]
    backsteine: list[Backstein]
    notizen: str