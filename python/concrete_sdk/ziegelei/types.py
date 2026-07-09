from dataclasses import dataclass
from datetime import date
from typing import Literal, Annotated

@dataclass
class Backstein:
    bezeichnung: str
    zusatz_kuerzel: str
    hoehe: float
    breite: float
    nut_und_kamm: bool
    def generate_text(self) -> str:
        return f"{self.bezeichnung} {self.zusatz_kuerzel} ({self.hoehe}/{self.breite}){'N+K' if self.nut_und_kamm else ''}"

@dataclass
class Tonsturz:
    breite: Annotated[float, "Breite des Tonsturzes in cm"]
    hoehe: Annotated[float, "Höhe des Tonsturzes in cm"]
    laenge: Annotated[float, "Länge des Tonsturzes in m"]
    verfuegbar: Annotated[bool, "Gibt an, ob der Tonsturz verfügbar ist oder nicht"]


@dataclass
class Bestellung:
    firma: str
    datum: date
    baustelle_strasse: str
    baustelle_nr: str
    baustelle_plz: str
    telefon: str
    lieferdatum: date
    name: str
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
    tonstuerze: list[Tonsturz]
    notizen: str