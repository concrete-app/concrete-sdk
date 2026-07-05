from pydantic import BaseModel, Field
from datetime import date, datetime, timedelta
from google.cloud.firestore_v1.client import Client
import json

from google.cloud import secretmanager
from google.oauth2 import service_account
from googleapiclient.discovery import build


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
    positionierung: str = Field("", description="Market positioning, for grounding LLM prompts")
    angebot: str = Field("", description="Core offer, for grounding LLM prompts")

    def get_company_info(self) -> str:
        """Full text description of the company, for grounding LLM prompts."""
        referenzen = "\n".join(
            f'- {r.name_company} ({r.name_person}): "{r.aussage}" ({r.url})'
            for r in self.referenzen
        ) or "(noch keine oeffentlichen Referenzen)"
        mitarbeiter = ", ".join(self.mitarbeiter) or "(nicht angegeben)"
        return (
            f"Dienstleistung:\n{self.dienstleistung}\n\n"
            f"Positionierung:\n{self.positionierung}\n\n"
            f"Angebot:\n{self.angebot}\n\n"
            f"Team: {mitarbeiter}\n\n"
            f"Referenzen:\n{referenzen}"
        )


class EmailDraft(BaseModel):
    """The only fields the LLM is allowed to author. Deliberately excludes the
    footer/signature - that is always assembled by SenderConfig.render_footer(),
    never asked of the model. Pass this (not EmailMessage) to with_structured_output."""
    subject: str
    ansprache: str
    body: str


class SenderConfig(BaseModel):
    """Fixed identity of the single human who signs every outreach email. Plain
    data + one formatting method - deliberately kept out of with_structured_output
    so the sign-off can never be paraphrased, reordered, or vary between runs."""
    name: str
    role: str = ""
    company: str = ""
    signoff: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    address: str = ""

    def render_footer(self) -> str:
        lines = [self.signoff, "", self.name]
        if self.role:
            lines.append(self.role)
        lines.append("")
        if self.phone:
            lines.append(self.phone)
        if self.email:
            lines.append(f'<a href="mailto:{self.email}">{self.email}</a>')
        lines.append("")
        if self.website:
            lines.append(f'<a href="https://{self.website}">{self.website}</a>')
        company_line = " | ".join(part for part in (self.company, self.address) if part)
        if company_line:
            lines.append(company_line)
        return "\n".join(lines)


class EmailMessage(BaseModel):
    subject: str
    ansprache: str
    body: str
    footer: str

    def create_message(self) -> str:
        return f"{self.subject}\n\n{self.ansprache}\n\n{self.body}\n\n{self.footer}"



class Lead:
    def __init__(self, name_company: str, name_contact_person: str, email: str, fit_reason: str, id: str | None = None, db: Client | None = None):
        self.name_company = name_company
        self.name_contact_person = name_contact_person
        self.email = email
        self.fit_reason = fit_reason
        self.id = id
        self.db: Client | None = db
        self.messages: list[EmailMessage] = []
        self.responded: bool = False
        self.writing_attempts: int = 2
        self.next_writing_attempt: datetime | None = None

    @classmethod
    def get(cls, db: Client, lead_id: str) -> "Lead":
        """Fetch a lead by id."""
        lead = cls(id=lead_id, db=db, name_company="", name_contact_person="", email="", fit_reason="")
        lead.read_lead_from_firebase()
        return lead

    def _to_dict(self) -> dict:
        return {
            "name_company": self.name_company,
            "name_contact_person": self.name_contact_person,
            "email": self.email,
            "fit_reason": self.fit_reason,
            "messages": [m.model_dump(mode="json") for m in self.messages],
            "responded": self.responded,
            "writing_attempts": self.writing_attempts,
            "next_writing_attempt": self.next_writing_attempt,
        }

    def _load(self, data: dict) -> None:
        self.name_company = data["name_company"]
        self.name_contact_person = data["name_contact_person"]
        self.email = data["email"]
        self.fit_reason = data["fit_reason"]
        self.messages = [EmailMessage(**m) for m in data.get("messages", [])]
        self.responded = data.get("responded", False)
        self.writing_attempts = data.get("writing_attempts", 2)
        self.next_writing_attempt = data.get("next_writing_attempt")

    def read_lead_from_firebase(self) -> None:
        """Refresh this instance in place - e.g. to pick up a reply before drafting the next email."""
        doc = self.db.collection("marketing").document(self.id).get()
        if not doc.exists:
            raise KeyError(f"Lead {self.id!r} not found in marketing collection")
        self._load(doc.to_dict())

    def write_lead_to_firebase(self) -> None:
        """Create or fully overwrite this lead's document - the single source of truth for it.

        If no id is set yet, Firestore assigns one and it's stored back onto this instance.
        """
        doc_ref = self.db.collection("marketing").document(self.id) if self.id else self.db.collection("marketing").document()
        self.id = doc_ref.id
        doc_ref.set(self._to_dict())

    def update_lead_in_firebase(self, **fields) -> None:
        """Patch specific fields without rewriting the whole document."""
        self.db.collection("marketing").document(self.id).update(fields)

    def mark_responded(self) -> None:
        """Flag this lead as responded, stopping the outreach sequence."""
        self.responded = True
        self.update_lead_in_firebase(responded=True)


    def record_send(self, draft: EmailMessage, followup_days: int = 8) -> None:
        """Record a sent outreach message and schedule (or clear) the next attempt."""
        self.messages.append(draft)
        self.writing_attempts -= 1
        self.next_writing_attempt = (
            datetime.now() + timedelta(days=followup_days) if self.writing_attempts > 0 else None
        )
        self.update_lead_in_firebase(
            messages=[m.model_dump(mode="json") for m in self.messages],
            writing_attempts=self.writing_attempts,
            next_writing_attempt=self.next_writing_attempt,
        )