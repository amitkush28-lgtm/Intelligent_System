"""
Congress.gov API (api.congress.gov) — Official Library of Congress API.
Replaces the discontinued ProPublica Congress API.
Free API key from https://api.congress.gov/sign-up/
Covers bills, amendments, votes, members, committees.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any

import httpx

logger = logging.getLogger(__name__)

CONGRESS_BASE = "https://api.congress.gov/v3"


async def fetch_congress_events(
    timeout: float = 30.0,
) -> List[Dict[str, Any]]:
    """
    Fetch recent US Congressional activity from Congress.gov API.
    Requires CONGRESS_API_KEY environment variable.
    Get a free key at https://api.congress.gov/sign-up/
    """
    api_key = os.environ.get("CONGRESS_API_KEY", "")
    if not api_key:
        logger.warning("CONGRESS_API_KEY not set, skipping Congress.gov source")
        return []

    events = []
    params_base = {"api_key": api_key, "format": "json", "limit": 50}

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        # 1. Recent bills
        try:
            resp = await client.get(
                f"{CONGRESS_BASE}/bill",
                params={**params_base, "sort": "updateDate+desc"},
            )
            if resp.status_code == 200:
                data = resp.json()
                bills = data.get("bills", [])
                for bill in bills[:30]:
                    try:
                        title = bill.get("title", "")
                        if not title:
                            continue

                        bill_type = bill.get("type", "")
                        bill_number = bill.get("number", "")
                        congress = bill.get("congress", "")
                        update_date = bill.get("updateDate", "")
                        latest_action = bill.get("latestAction", {})
                        action_text = latest_action.get("text", "")
                        action_date = latest_action.get("actionDate", "")

                        bill_id = f"{bill_type}{bill_number}-{congress}"

                        raw_text = f"US Congress: {title} ({bill_id})"
                        if action_text:
                            raw_text += f". Latest action: {action_text}"

                        timestamp = datetime.utcnow()
                        if action_date:
                            try:
                                timestamp = datetime.strptime(action_date, "%Y-%m-%d")
                            except ValueError:
                                pass

                        # Determine severity based on action
                        severity = "routine"
                        action_lower = action_text.lower()
                        if any(w in action_lower for w in ["passed", "signed", "enacted", "veto"]):
                            severity = "significant"
                        elif any(w in action_lower for w in ["committee", "referred", "reported"]):
                            severity = "notable"

                        events.append({
                            "id": f"congress-bill-{bill_id}-{action_date or 'latest'}",
                            "source": "congress_gov",
                            "source_detail": bill.get("url", "congress.gov"),
                            "timestamp": timestamp,
                            "domain": "political",
                            "event_type": "legislation",
                            "severity": severity,
                            "entities": [{"name": bill_id, "type": "law", "role": "subject"}],
                            "raw_text": raw_text,
                        })
                    except Exception as e:
                        logger.debug(f"Error parsing Congress bill: {e}")
                        continue
            else:
                logger.warning(f"Congress.gov bills HTTP {resp.status_code}")
        except Exception as e:
            logger.warning(f"Congress.gov bills error: {e}")

        # 2. Recent actions (floor activity)
        try:
            today = datetime.utcnow().strftime("%Y-%m-%dT00:00:00Z")
            yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")

            resp = await client.get(
                f"{CONGRESS_BASE}/daily-congressional-record",
                params={**params_base},
            )
            if resp.status_code == 200:
                data = resp.json()
                records = data.get("dailyCongressionalRecord", [])
                for record in records[:10]:
                    try:
                        issue_date = record.get("issueDate", "")
                        issue_number = record.get("issueNumber", "")
                        congress = record.get("congress", "")
                        session = record.get("sessionNumber", "")

                        raw_text = f"Congressional Record Vol. {congress}, Session {session}, Issue {issue_number} ({issue_date})"

                        timestamp = datetime.utcnow()
                        if issue_date:
                            try:
                                timestamp = datetime.strptime(issue_date, "%Y-%m-%d")
                            except ValueError:
                                pass

                        events.append({
                            "id": f"congress-record-{congress}-{session}-{issue_number}",
                            "source": "congress_gov",
                            "source_detail": "congress.gov/congressional-record",
                            "timestamp": timestamp,
                            "domain": "political",
                            "event_type": "congressional_record",
                            "severity": "routine",
                            "entities": [{"name": "US Congress", "type": "organization", "role": "publisher"}],
                            "raw_text": raw_text,
                        })
                    except Exception as e:
                        logger.debug(f"Error parsing Congressional Record: {e}")
                        continue
        except Exception as e:
            logger.debug(f"Congress.gov records error: {e}")

    logger.info(f"Congress.gov: returning {len(events)} events")
    return events
