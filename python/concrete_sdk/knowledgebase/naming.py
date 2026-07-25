"""Flat, collision-safe GCS object names for scraped knowledgebase content.

Everything lands directly under one prefix (no per-domain subfolders), so names
must disambiguate both domain and path on their own. The hash suffix guards
against slugification collisions (e.g. trailing-slash variants of the same path).
"""
import hashlib
import os
import re
from urllib.parse import unquote, urlparse


def sanitize_domain(domain: str) -> str:
    return re.sub(r"[^a-zA-Z0-9.-]", "_", domain)


def url_hash(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]


def slugify_path(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return path.replace("/", "_") if path else "index"


def flat_page_name(url: str, domain: str) -> str:
    return f"{sanitize_domain(domain)}--{slugify_path(url)}-{url_hash(url)}.md"


def flat_pdf_name(url: str, domain: str) -> str:
    filename = unquote(os.path.basename(urlparse(url).path)) or "download.pdf"
    stem, ext = os.path.splitext(filename)
    if ext.lower() != ".pdf":
        ext = ".pdf"
    stem = re.sub(r"[^a-zA-Z0-9._-]", "_", stem) or "download"
    return f"{sanitize_domain(domain)}--{stem}-{url_hash(url)}{ext}"
