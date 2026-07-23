export class Backstein {
  bezeichnung: string;
  zusatzKuerzel: string;
  hoehe: number;
  breite: number;
  nutUndKamm: boolean;

  constructor(props: {
    bezeichnung: string;
    zusatzKuerzel: string;
    hoehe: number;
    breite: number;
    nutUndKamm: boolean;
  }) {
    this.bezeichnung = props.bezeichnung;
    this.zusatzKuerzel = props.zusatzKuerzel;
    this.hoehe = props.hoehe;
    this.breite = props.breite;
    this.nutUndKamm = props.nutUndKamm;
  }

  generateText(): string {
    return `${this.bezeichnung} ${this.zusatzKuerzel} (${this.hoehe}/${this.breite})${this.nutUndKamm ? "N+K" : ""}`;
  }
}

export interface Tonsturz {
  /** Breite des Tonsturzes in cm */
  breite: number;
  /** Höhe des Tonsturzes in cm */
  hoehe: number;
  /** Länge des Tonsturzes in m */
  laenge: number;
  /** Gibt an, ob der Tonsturz verfügbar ist oder nicht */
  verfuegbar: boolean;
}

export type Zufahrt =
  | "Solo-Fahrzeug (3-Achser) ca. 17 Paletten"
  | "Zufahrt mit Anhänderzug ca. 29 Paletten"
  | "Ablad mit Kranwagen (4 Paletten weniger)";

export type LieferRichtzeit = "07:00" | "09:00 - 12:00" | "Nachmittag";

/** Eine einzelne Bestellzeile, unabhängig von der Produktkategorie (Backstein, Tonsturz,
 * Murfor, Thermur plus, ...) -- ersetzt die früheren getrennten `backsteine`/`tonstuerze`-Arrays,
 * die kein Mengenfeld hatten und pro Kategorie eigene Handhabung im Aufrufer erzwangen. */
export interface BestellPosition {
  kategorie: string;
  produktText: string;
  anzahl: number;
  einheit: string;
}

export interface Bestellung {
  firma: string;
  datum: Date;
  baustelleStrasse: string;
  baustelleNr: string;
  baustellePlz: string;
  telefon: string;
  email: string;
  lieferdatum: Date;
  name: string;
  frankoBauOderAbgeholt: boolean;
  zufahrt: Zufahrt;
  lieferRichtzeiten: LieferRichtzeit;
  positionen: BestellPosition[];
  notizen: string;
}
