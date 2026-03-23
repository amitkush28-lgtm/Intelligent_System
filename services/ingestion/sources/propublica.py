"""
ProPublica Congress API — Free, US legislative tracking.
Bills, votes, member data.
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

import httpx

logger = logging.getLogger(__name__)

PROPUBLICA_BASE_URL = "https://api.propublica.org/congress/v1"

# ProPublica requires an API key but it's free — use env var
# For now we use the public endpoints that don't require a key
PROPUBLICA_PUBLIC_URL = "https://projects.propublica.org/api"


async def fetch_propublica_events(
    timeout: float = 30.0,
) -> List[Dict[str, Any]]:
    """
    Fetch recent US Congressional activity.
    Uses ProPublica's public data endpoints.
    Returns list of event dicts.
    """
    events = []

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        # Fetch recent bills
        try:
            resp = await client.get(
                f"{PROPUBLICA_BASE_URL}/118/both/bills/active.json",
                headers={"Accept": "application/json"},
            )

            if resp.status_code == 200:
                data = resp.json()
                bills = data.get("results", [{}])[0].get("bills", []) if data.get("results") else []

                for bill in bills[:30]:
                    try:
                        title = bill.get("title", "") or bill.get("short_title", "")
                        if not title:
                            continue

                        bill_id = bill.get("bill_id", "")
                        sponsor = bill.get("sponsor_title", "") + " " + bill.get("sponsor_name", "")
                        committee = bill.get("committees", "")
                        introduced = bill.get("introduced_date", "")
                        latest_action = bill.get("latest_major_action", "")
                        latest_action_date = bill.get("latest_major_action_date", "")

                        raw_text = f"US Congress: {title} ({bill_id})"
                        if sponsor.strip():
                            raw_text += f". Sponsored by {sponsor.strip()}"
                        if latest_action:
                            raw_text += f". Latest action: {latest_action}"

                        timestamp = datetime.utcnow()
                        if latest_action_date:
                            try:
                                timestamp = datetime.strptime(latest_action_date, "%Y-%m-%d")
                            except ValueError:
                                pass

                        entities = [{"name": bill_id, "type": "law", "role": "subject"}]
                        if sponsor.strip():
                            entities.append({"name": sponsor.strip(), "type": "person", "role": "sponsor"})

                        events.append({
                            "source": "propublica",
                            "source_detail": bill.get("congressdotgov_url", "propublica.org"),
                            "timestamp": timestamp,
                            "domain": "political",
                            "event_type": "legislation",
                            "severity": "notable",
                            "entities": entities,
                            "raw_text": raw_text,
                            "metadata": {
                                "bill_id": bill_id,
                                "committee": committee,
                                "latest_action": latest_action,
                                "active": bill.get("active", False),
                            },
                        })
                    except Exception as e:
                        logger.debug(f"Error parsing ProPublica bill: {e}")
                        continue

            elif resp.status_code == 403:
                logger.info("ProPublica API key not configured, using limited access")
            else:
                logger.warning(f"ProPublica HTTP {resp.status_code}")

        except httpx.TimeoutException:
            logger.warning("ProPublica timeout")
        except Exception as e:
            logger.warning(f"ProPublica error: {e}")

    logger.info(f"ProPublica: returning {len(events)} events")
    return events
