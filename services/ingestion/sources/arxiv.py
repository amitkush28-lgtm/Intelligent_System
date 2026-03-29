"""
ArXiv API — Free, no API key required.
Tracks research paper trends as early warning signals for technology disruption.
Every major tech disruption was visible in research paper trends years before market impact.
"""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import List, Dict, Any

import httpx

logger = logging.getLogger(__name__)

ARXIV_API_URL = "http://export.arxiv.org/api/query"

# Categories to monitor — mapped to intelligence domains
ARXIV_CATEGORIES = {
    # AI and Machine Learning
    "cs.AI": {"domain": "technology", "label": "Artificial Intelligence"},
    "cs.CL": {"domain": "technology", "label": "Computation and Language (NLP)"},
    "cs.LG": {"domain": "technology", "label": "Machine Learning"},
    "cs.CV": {"domain": "technology", "label": "Computer Vision"},
    "cs.CR": {"domain": "technology", "label": "Cryptography and Security"},
    # Quantum
    "quant-ph": {"domain": "technology", "label": "Quantum Physics"},
    # Biology and health
    "q-bio.PE": {"domain": "health", "label": "Populations and Evolution"},
    "q-bio.GN": {"domain": "health", "label": "Genomics"},
    # Physics / Energy
    "physics.plasm-ph": {"domain": "economic", "label": "Plasma Physics (Fusion)"},
    "cond-mat.supr-con": {"domain": "technology", "label": "Superconductivity"},
    # Economics
    "econ.GN": {"domain": "economic", "label": "General Economics"},
    "q-fin.GN": {"domain": "market", "label": "Quantitative Finance"},
}

# Keywords that signal high-impact research
HIGH_IMPACT_KEYWORDS = [
    "breakthrough", "state-of-the-art", "surpass", "outperform",
    "novel", "first", "unprecedented", "scalable", "practical",
    "human-level", "superhuman", "zero-shot", "efficiency",
    "orders of magnitude", "10x", "100x",
]

# Max papers per category per fetch
MAX_PAPERS_PER_CATEGORY = 15


def _extract_papers_from_xml(xml_text: str) -> List[Dict[str, Any]]:
    """Parse ArXiv Atom XML response into paper dicts."""
    papers = []

    try:
        root = ET.fromstring(xml_text)
        ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

        for entry in root.findall("atom:entry", ns):
            try:
                title_el = entry.find("atom:title", ns)
                summary_el = entry.find("atom:summary", ns)
                published_el = entry.find("atom:published", ns)
                id_el = entry.find("atom:id", ns)

                title = title_el.text.strip().replace("\n", " ") if title_el is not None and title_el.text else ""
                summary = summary_el.text.strip().replace("\n", " ") if summary_el is not None and summary_el.text else ""
                published = published_el.text.strip() if published_el is not None and published_el.text else ""
                paper_id = id_el.text.strip() if id_el is not None and id_el.text else ""

                # Extract categories
                categories = []
                for cat in entry.findall("atom:category", ns):
                    term = cat.get("term", "")
                    if term:
                        categories.append(term)

                # Extract authors
                authors = []
                for author in entry.findall("atom:author", ns):
                    name_el = author.find("atom:name", ns)
                    if name_el is not None and name_el.text:
                        authors.append(name_el.text.strip())

                # Parse published date
                pub_date = None
                if published:
                    try:
                        pub_date = datetime.fromisoformat(published.replace("Z", "+00:00"))
                    except ValueError:
                        pass

                papers.append({
                    "title": title,
                    "summary": summary[:500],
                    "published": pub_date or datetime.utcnow(),
                    "paper_id": paper_id,
                    "categories": categories,
                    "authors": authors[:5],
                    "url": paper_id.replace("http://arxiv.org/abs/", "https://arxiv.org/abs/"),
                })
            except Exception as e:
                logger.debug(f"Error parsing ArXiv entry: {e}")
                continue
    except ET.ParseError as e:
        logger.error(f"ArXiv XML parse error: {e}")

    return papers


def _has_high_impact_signals(title: str, summary: str) -> bool:
    """Check if paper title/summary contains high-impact keywords."""
    text = (title + " " + summary).lower()
    return any(kw.lower() in text for kw in HIGH_IMPACT_KEYWORDS)


def _determine_severity(paper: Dict, category_info: Dict) -> str:
    """Determine event severity based on paper signals."""
    if _has_high_impact_signals(paper["title"], paper["summary"]):
        return "elevated"
    return "routine"


async def fetch_arxiv_events(
    timeout: float = 45.0,
) -> List[Dict[str, Any]]:
    """
    Fetch recent papers from ArXiv across monitored categories.
    Returns events for papers with high-impact signals.
    """
    events = []

    # Only look at papers from last 7 days
    cutoff = datetime.utcnow() - timedelta(days=7)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for category, info in ARXIV_CATEGORIES.items():
            try:
                params = {
                    "search_query": f"cat:{category}",
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                    "max_results": MAX_PAPERS_PER_CATEGORY,
                }

                resp = await client.get(ARXIV_API_URL, params=params)
                resp.raise_for_status()

                papers = _extract_papers_from_xml(resp.text)

                for paper in papers:
                    # Skip old papers
                    if paper["published"] < cutoff:
                        continue

                    # For non-high-impact papers, only include from key AI categories
                    is_high_impact = _has_high_impact_signals(paper["title"], paper["summary"])
                    is_key_category = category in ("cs.AI", "cs.CL", "cs.LG", "quant-ph")

                    if not is_high_impact and not is_key_category:
                        continue

                    severity = _determine_severity(paper, info)

                    raw_text = (
                        f"ArXiv Research: [{info['label']}] {paper['title']}. "
                        f"Authors: {', '.join(paper['authors'][:3])}{'...' if len(paper['authors']) > 3 else ''}. "
                        f"Summary: {paper['summary'][:300]}"
                    )

                    entities = [
                        {"name": "ArXiv", "type": "organization", "role": "source"},
                        {"name": info["label"], "type": "research_field", "role": "category"},
                    ]
                    for author in paper["authors"][:2]:
                        entities.append({"name": author, "type": "person", "role": "researcher"})

                    events.append({
                        "source": "arxiv",
                        "source_detail": paper["url"],
                        "timestamp": paper["published"],
                        "domain": info["domain"],
                        "event_type": "research_publication",
                        "severity": severity,
                        "entities": entities,
                        "raw_text": raw_text,
                        "metadata": {
                            "paper_id": paper["paper_id"],
                            "title": paper["title"],
                            "categories": paper["categories"],
                            "authors": paper["authors"],
                            "high_impact": is_high_impact,
                            "arxiv_category": category,
                        },
                    })

            except httpx.HTTPStatusError as e:
                logger.warning(f"ArXiv HTTP error for {category}: {e.response.status_code}")
            except httpx.TimeoutException:
                logger.warning(f"ArXiv timeout for category {category}")
            except Exception as e:
                logger.debug(f"ArXiv error for {category}: {e}")

    logger.info(f"ArXiv: returning {len(events)} research signals")
    return events
