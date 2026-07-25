"""Website crawler for knowledgebase ingestion.

Ported from the standalone website_crawler repo: BFS-crawls a domain for page
markdown and linked PDFs, but uploads everything directly to GCS (flat, under
one prefix) instead of writing to local disk. Importable as a library call from
a Cloud Task handler, not a script.
"""
import asyncio
import random
from urllib.parse import urljoin, urlparse

import httpx
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from crawl4ai.deep_crawling import BFSDeepCrawlStrategy
from crawl4ai.deep_crawling.filters import DomainFilter, FilterChain, URLPatternFilter

from .gcs import upload_bytes
from .naming import flat_pdf_name, flat_page_name


class WebsiteKbScraper:
    def __init__(
        self,
        base_url: str,
        bucket_name: str,
        prefix: str = "scraping",
        max_depth: int = 3,
        semaphore_count: int = 4,
        mean_delay: float = 0.5,
        max_range: float = 1.0,
        pdf_concurrency: int = 4,
    ):
        self.base_url = base_url
        self.bucket_name = bucket_name
        self.prefix = prefix.strip("/")
        self.domain = urlparse(base_url).netloc
        self.max_depth = max_depth
        self.semaphore_count = semaphore_count
        self.mean_delay = mean_delay
        self.max_range = max_range
        self.pdf_concurrency = pdf_concurrency

    async def run(self) -> dict:
        results = await self._crawl_pages()
        page_uris = self._save_pages(results)
        pdf_urls = self._collect_pdf_links(results)
        pdf_uris, pdfs_failed = await self._download_pdfs(pdf_urls)
        return {
            "domain": self.domain,
            "gcs_uris": page_uris + pdf_uris,
            "pages_saved": len(page_uris),
            "pdfs_found": len(pdf_urls),
            "pdfs_saved": len(pdf_uris),
            "pdfs_failed": pdfs_failed,
        }

    async def _crawl_pages(self):
        filter_chain = FilterChain([
            DomainFilter(allowed_domains=[self.domain]),
            URLPatternFilter(patterns=["*.pdf"], reverse=True),
        ])
        strategy = BFSDeepCrawlStrategy(
            max_depth=self.max_depth,
            filter_chain=filter_chain,
            include_external=False,
        )
        run_config = CrawlerRunConfig(
            deep_crawl_strategy=strategy,
            stream=False,
            semaphore_count=self.semaphore_count,
            mean_delay=self.mean_delay,
            max_range=self.max_range,
        )
        async with AsyncWebCrawler() as crawler:
            return await crawler.arun(self.base_url, config=run_config)

    def _save_pages(self, results) -> list[str]:
        uris = []
        for result in results:
            if not result.success:
                continue
            blob_name = flat_page_name(result.url, self.domain)
            uri = upload_bytes(
                self.bucket_name,
                f"{self.prefix}/{blob_name}",
                result.markdown.raw_markdown.encode("utf-8"),
                "text/markdown",
            )
            uris.append(uri)
        return uris

    def _collect_pdf_links(self, results) -> set[str]:
        pdf_urls = set()
        for result in results:
            if not result.success:
                continue
            links = result.links.get("internal", []) + result.links.get("external", [])
            for link in links:
                href = link.get("href")
                if not href:
                    continue
                absolute_url = urljoin(result.url, href)
                if urlparse(absolute_url).path.lower().endswith(".pdf"):
                    pdf_urls.add(absolute_url)
        return pdf_urls

    async def _download_pdfs(self, pdf_urls: set[str]) -> tuple[list[str], int]:
        semaphore = asyncio.Semaphore(self.pdf_concurrency)
        uris: list[str] = []
        failed = 0

        async def download(client: httpx.AsyncClient, url: str) -> None:
            nonlocal failed
            async with semaphore:
                await asyncio.sleep(random.uniform(0.3, 1.0))
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    if response.content.startswith(b"%PDF"):
                        blob_name = flat_pdf_name(url, self.domain)
                        uri = upload_bytes(
                            self.bucket_name,
                            f"{self.prefix}/{blob_name}",
                            response.content,
                            "application/pdf",
                        )
                        uris.append(uri)
                    else:
                        failed += 1
                except httpx.HTTPError:
                    failed += 1

        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            await asyncio.gather(*(download(client, url) for url in pdf_urls))

        return uris, failed
