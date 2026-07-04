from pydantic import BaseModel, Field
from datetime import date
from dataclasses import dataclass, field
from datetime import datetime

class Referenz(BaseModel):
    datum: date | None = Field(None, description="Date of the reference")
    name_company: str = Field(..., description="Name of the reference")
    name_person: str = Field(..., description="Person associated with the reference")
    url: str = Field(..., description="URL of the reference")
    aussage: str = Field(..., description="Statement or testimonial from the reference")

class Company(BaseModel):
    referenzen: list[Referenz] = Field(default_factory=list)
    mitarbeiter: list[str] = Field(default_factory=list, description="List of employees associated with the Company")
    dienstleistung: str = Field(..., description="Description of the service provided by the Company")

    def get_company_info(self) -> str:
        """Full text description of the company, for grounding LLM prompts."""
        referenzen = "\n".join(
            f'- {r.name_company} ({r.name_person}): "{r.aussage}" ({r.url})'
            for r in self.referenzen
        ) or "(noch keine oeffentlichen Referenzen)"
        mitarbeiter = ", ".join(self.mitarbeiter) or "(nicht angegeben)"
        return (
            f"Dienstleistung:\n{self.dienstleistung}\n\n"
            f"Team: {mitarbeiter}\n\n"
            f"Referenzen:\n{referenzen}"
        )
    


class EmailMessage(BaseModel):
    subject: str
    ansprache: str
    body: str
    footer: str

    def create_message(self) -> str:
        return f"{self.subject}\n\n{self.ansprache}\n\n{self.body}\n\n{self.footer}"


@dataclass
class Lead:
    id: str
    name_company: str
    name_contact_person: str
    email: str
    fit_reason: str
    messages: list[EmailMessage] = field(default_factory=list)
    responded: bool = False
    writing_attempts: int = 3
    next_writing_attempt: datetime | None = None