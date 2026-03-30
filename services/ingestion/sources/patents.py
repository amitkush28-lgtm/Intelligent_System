"""
USPTO Patent Data — Free, no API key required.

Tracks patent grants and applications as forward-looking signals for
technology commercialization, corporate strategy, and competitive dynamics.

Primary: PatentsView API (granted patents, structured search)
Fallback: USPTO RSS feeds (weekly bulk grant/application listings)

Patents are a leading indicator: filing-to-grant is 2-3 years, so grants
today reflect strategic bets made years ago. Clusters of patents in a
domain signal serious commercial intent, not just research curiosity.
"""

import hashlib
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import List, Dict, Any

import httpx

logger = logging.getLogger(__name__)

# ── PatentsView API (primary) ──────────────────────────────────────────
# Free, no API key, up to 45 requests/minute
# Docs: https://patentsview.org/apis/api-endpoints
PATENTSVIEW_URL = "https://api.patentsview.org/patents/query"

# Strategic technology domains to monitor
# Each query targets patents that signal emerging commercial capability
PATENT_QUERIES = {
    "artificial_intelligence": {
        "domain": "technology",
        "label": "AI & Machine Learning Patents",
        "cpc_prefixes": ["G06N"],  # Machine learning, neural networks
        "keywords": ["artificial intelligence", "machine learning", "neural network",
                      "deep learning", "language model", "transformer"],
    },
    "quantum_computing": {
        "domain": "technology",
        "label": "Quantum Computing Patents",
        "cpc_prefixes": ["G06N10"],  # Quantum computing
        "keywords": ["quantum computing", "qubit", "quantum processor",
                      "quantum circuit", "quantum error correction"],
    },
    "biotech_genomics": {
        "domain": "health",
        "label": "Biotech & Genomics Patents",
        "cpc_prefixes": ["C12N15", "C12Q1/68"],  # Gene tech, nucleic acid testing
        "keywords": ["gene therapy", "CRISPR", "mRNA", "genomic",
                      "cell therapy", "immunotherapy"],
    },
    "energy_storage": {
        "domain": "economic",
        "label": "Energy Storage & Battery Patents",
        "cpc_prefixes": ["H01M"],  # Electrochemical energy sources
        "keywords": ["solid state battery", "lithium", "energy storage",
                      "battery", "fuel cell", "supercapacitor"],
    },
    "semiconductors": {
        "domain": "technology",
        "label": "Semiconductor & Chip Patents",
        "cpc_prefixes": ["H01L"],  # Semiconductor devices
        "keywords": ["semiconductor", "transistor", "chip", "wafer",
                      "EUV", "lithography", "3nm", "2nm"],
    },
    "autonomous_systems": {
        "domain": "technology",
        "label": "Autonomous Systems & Robotics Patents",
        "cpc_prefixes": ["B60W60", "B25J9"],  # Autonomous vehicles, robots
        "keywords": ["autonomous vehicle", "self-driving", "robotics",
                      "drone", "unmanned", "lidar"],
    },
    "cybersecurity": {
        "domain": "technology",
        "label": "Cybersecurity Patents",
        "cpc_prefixes": ["H04L9", "G06F21"],  # Crypto, security
        "keywords": ["encryption", "cybersecurity", "zero trust",
                      "authentication", "intrusion detection"],
    },
    "space_defense": {
        "domain": "geopolitical",
        "label": "Space & Defense Technology Patents",
        "cpc_prefixes": ["B64G"],  # Cosmonautics, space vehicles
        "keywords": ["satellite", "space launch", "hypersonic",
                      "directed energy", "missile defense"],
    },
}

# Major assignees to track — shifts in their patent portfolios signal strategy
STRATEGIC_ASSIGNEES = {
    "Google", "Microsoft", "Apple", "Amazon", "Meta",
    "NVIDIA", "Intel", "Samsung", "TSMC", "IBM",
    "Qualcomm", "Huawei", "Tencent", "Alibaba", "Baidu",
    "Tesla", "SpaceX", "Lockheed Martin", "Raytheon",
    "Pfizer", "Moderna", "Johnson & Johnson",
}

# High-signal keywords that suggest breakthrough or strategic importance
HIGH_IMPACT_SIGNALS = [
    "breakthrough", "novel", "first", "unprecedented",
    "orders of magnitude", "disruptive", "revolutionary",
    "high efficiency", "low cost", "scalable",
]

MAX_PATENTS_PER_QUERY = 25


def _patent_id(patent_number: str) -> str:
    """Generate deterministic event ID from patent number."""
    return f"patent-{patent_number}"


def _hash_id(text: str) -> str:
    """Fallback ID from text hash."""
    return f"patent-{hashlib.sha256(text.encode()).hexdigest()[:12]}"


def _is_strategic_assignee(assignee_name: str) -> bool:
    """Check if patent assignee is a strategically important company."""
    name_lower = assignee_name.lower()
    return any(sa.lower() in name_lower for sa in STRATEGIC_ASSIGNEES)


def _has_high_impact_signals(title: str, abstract: str) -> bool:
    """Check if patent text suggests breakthrough or high importance."""
    text = (title + " " + abstract).lower()
    return any(kw in text for kw in HIGH_IMPACT_SIGNALS)


def _determine_severity(patent: Dict, query_info: Dict) -> str:
    """Determine event severity based on patent signals."""
    title = patent.get("title", "")
    abstract = patent.get("abstract", "")

    if _has_high_impact_signals(title, abstract):
        return "elevated"

    # Strategic assignee patents are always at least noteworthy
    for assignee in patent.get("assignees", []):
        if _is_strategic_assignee(assignee):
            return "elevated"

    return "routine"


async def _fetch_patentsview(client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    """Fetch recent patents from PatentsView API.

    Uses keyword-based queries since PatentsView's CPC search
    works best with text matching on titles and abstracts.
    """
    events = []
    cutoff = datetime.utcnow() - timedelta(days=14)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    for query_key, info in PATENT_QUERIES.items():
        try:
            # Build keyword OR query for PatentsView
            keyword_clauses = []
            for kw in info["keywords"][:4]:  # Limit to avoid query-too-long
                keyword_clauses.append(
                    {"_or": [
                        {"_text_any": {"patent_title": kw}},
                        {"_text_any": {"patent_abstract": kw}},
                    ]}
                )

            query_body = {
                "q": {
                    "_and": [
                        {"_gte": {"patent_date": cutoff_str}},
                        {"_or": keyword_clauses},
                    ]
                },
                "f": [
                    "patent_number", "patent_title", "patent_abstract",
                    "patent_date", "patent_type",
                    "assignee_organization", "assignee_country",
                    "inventor_first_name", "inventor_last_name",
                    "cpc_group_id",
                ],
                "o": {"per_page": MAX_PATENTS_PER_QUERY},
                "s": [{"patent_date": "desc"}],
            }

            resp = await client.post(
                PATENTSVIEW_URL,
                json=query_body,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

            patents = data.get("patents", [])
            if not patents:
                continue

            for pat in patents:
                patent_number = pat.get("patent_number", "")
                if not patent_number:
                    continue

                title = pat.get("patent_title", "")
                abstract = pat.get("patent_abstract", "") or ""

                # Parse date
                date_str = pat.get("patent_date", "")
                try:
                    pub_date = datetime.strptime(date_str, "%Y-%m-%d") if date_str else datetime.utcnow()
                except ValueError:
                    pub_date = datetime.utcnow()

                if pub_date < cutoff:
                    continue

                # Extract assignees
                assignees_raw = pat.get("assignees", []) or []
                assignees = []
                assignee_countries = []
                for a in assignees_raw:
                    org = a.get("assignee_organization", "")
                    if org:
                        assignees.append(org)
                    country = a.get("assignee_country", "")
                    if country:
                        assignee_countries.append(country)

                # Extract inventors
                inventors_raw = pat.get("inventors", []) or []
                inventors = []
                for inv in inventors_raw[:3]:
                    first = inv.get("inventor_first_name", "")
                    last = inv.get("inventor_last_name", "")
                    if first or last:
                        inventors.append(f"{first} {last}".strip())

                # Extract CPC codes
                cpcs_raw = pat.get("cpcs", []) or []
                cpc_codes = [c.get("cpc_group_id", "") for c in cpcs_raw if c.get("cpc_group_id")]

                # Build patent dict for severity check
                patent_dict = {
                    "title": title,
                    "abstract": abstract,
                    "assignees": assignees,
                }

                severity = _determine_severity(patent_dict, info)

                # Skip routine patents unless from strategic assignees
                is_strategic = any(_is_strategic_assignee(a) for a in assignees)
                is_high_impact = _has_high_impact_signals(title, abstract)
                if severity == "routine" and not is_strategic and not is_high_impact:
                    continue

                assignee_str = ", ".join(assignees[:2]) if assignees else "Unknown assignee"
                raw_text = (
                    f"USPTO Patent Grant: [{info['label']}] US{patent_number} — {title}. "
                    f"Assignee: {assignee_str}. "
                    f"Abstract: {abstract[:300]}"
                )

                entities = [
                    {"name": "USPTO", "type": "organization", "role": "source"},
                    {"name": info["label"], "type": "technology_domain", "role": "category"},
                ]
                for assignee in assignees[:2]:
                    entities.append({"name": assignee, "type": "organization", "role": "assignee"})
                for inventor in inventors[:2]:
                    entities.append({"name": inventor, "type": "person", "role": "inventor"})

                events.append({
                    "id": _patent_id(patent_number),
                    "source": "uspto_patents",
                    "source_detail": f"https://patents.google.com/patent/US{patent_number}",
                    "timestamp": pub_date,
                    "domain": info["domain"],
                    "event_type": "patent_grant",
                    "severity": severity,
                    "entities": entities,
                    "raw_text": raw_text,
                    "metadata": {
                        "patent_number": patent_number,
                        "title": title,
                        "assignees": assignees,
                        "assignee_countries": assignee_countries,
                        "inventors": inventors,
                        "cpc_codes": cpc_codes[:5],
                        "patent_type": pat.get("patent_type", ""),
                        "query_domain": query_key,
                        "strategic_assignee": is_strategic,
                        "high_impact": is_high_impact,
                    },
                })

            logger.debug(f"PatentsView [{query_key}]: {len(patents)} results, {len([e for e in events if e['metadata'].get('query_domain') == query_key])} kept")

        except httpx.HTTPStatusError as e:
            logger.warning(f"PatentsView HTTP error for {query_key}: {e.response.status_code}")
        except httpx.TimeoutException:
            logger.warning(f"PatentsView timeout for {query_key}")
        except Exception as e:
            logger.debug(f"PatentsView error for {query_key}: {e}")

    return events


# ── USPTO RSS fallback ─────────────────────────────────────────────────
USPTO_RSS_URLS = [
    # Weekly patent grant gazette
    "https://www.uspto.gov/rss/feeds/patgrant.xml",
    # Patent application publications
    "https://www.uspto.gov/rss/feeds/patapp.xml",
]


async def _fetch_uspto_rss(client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    """Fallback: fetch patent data from USPTO RSS feeds.

    Less targeted than PatentsView but catches high-level trends.
    """
    events = []
    cutoff = datetime.utcnow() - timedelta(days=14)

    for url in USPTO_RSS_URLS:
        try:
            resp = await client.get(url)
            resp.raise_for_status()

            root = ET.fromstring(resp.text)
            channel = root.find("channel")
            if channel is None:
                continue

            for item in channel.findall("item"):
                title_el = item.find("title")
                desc_el = item.find("description")
                link_el = item.find("link")
                pub_el = item.find("pubDate")

                title = title_el.text.strip() if title_el is not None and title_el.text else ""
                desc = desc_el.text.strip() if desc_el is not None and desc_el.text else ""
                link = link_el.text.strip() if link_el is not None and link_el.text else ""

                # Parse date
                pub_date = datetime.utcnow()
                if pub_el is not None and pub_el.text:
                    try:
                        # RSS dates like "Tue, 25 Mar 2026 00:00:00 EST"
                        from email.utils import parsedate_to_datetime
                        pub_date = parsedate_to_datetime(pub_el.text)
                    except Exception:
                        pass

                if pub_date.replace(tzinfo=None) < cutoff:
                    continue

                if not title:
                    continue

                # Determine if this is high-impact
                is_high_impact = _has_high_impact_signals(title, desc)
                has_strategic = any(sa.lower() in (title + " " + desc).lower() for sa in STRATEGIC_ASSIGNEES)

                if not is_high_impact and not has_strategic:
                    continue

                event_id = _hash_id(title + link)
                severity = "elevated" if is_high_impact or has_strategic else "routine"

                events.append({
                    "id": event_id,
                    "source": "uspto_patents",
                    "source_detail": link,
                    "timestamp": pub_date,
                    "domain": "technology",
                    "event_type": "patent_publication",
                    "severity": severity,
                    "entities": [
                        {"name": "USPTO", "type": "organization", "role": "source"},
                    ],
                    "raw_text": f"USPTO Patent Notice: {title}. {desc[:300]}",
                    "metadata": {
                        "source_feed": url,
                        "high_impact": is_high_impact,
                        "strategic_assignee": has_strategic,
                    },
                })

        except httpx.HTTPStatusError as e:
            logger.warning(f"USPTO RSS HTTP error: {e.response.status_code}")
        except httpx.TimeoutException:
            logger.warning(f"USPTO RSS timeout: {url}")
        except Exception as e:
            logger.debug(f"USPTO RSS error: {e}")

    return events


# ── Public entry point ─────────────────────────────────────────────────

async def fetch_patent_events(
    timeout: float = 60.0,
) -> List[Dict[str, Any]]:
    """
    Fetch recent patent grants and applications from USPTO.

    Strategy:
    1. Try PatentsView API (structured, keyword-filtered)
    2. Fall back to USPTO RSS if PatentsView returns nothing

    Returns events for patents with strategic importance signals.
    """
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        # Primary: PatentsView API
        events = await _fetch_patentsview(client)

        if events:
            logger.info(f"USPTO Patents (PatentsView): returning {len(events)} patent signals")
            return events

        # Fallback: RSS feeds
        logger.info("PatentsView returned no results, trying USPTO RSS fallback")
        events = await _fetch_uspto_rss(client)
        logger.info(f"USPTO Patents (RSS fallback): returning {len(events)} patent signals")
        return events
