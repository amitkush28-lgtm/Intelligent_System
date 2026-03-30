"""
CFTC Commitment of Traders — Free weekly CSV download.
Fund positioning data for the investor agent.
Shows how large speculators, commercials, and small traders are positioned
in futures markets.
"""

import csv
import io
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

import httpx

logger = logging.getLogger(__name__)

# CFTC provides data in multiple formats. We use the Disaggregated Futures-Only reports.
CFTC_CURRENT_URL = "https://www.cftc.gov/dea/newcot/f_disagg.txt"
# Alternative: combined futures+options
CFTC_COMBINED_URL = "https://www.cftc.gov/dea/newcot/f_disagg.txt"

# Key contracts to track
KEY_CONTRACTS = {
    "EURO FX": {"domain": "market", "asset": "EUR/USD futures"},
    "JAPANESE YEN": {"domain": "market", "asset": "JPY futures"},
    "BRITISH POUND": {"domain": "market", "asset": "GBP futures"},
    "GOLD": {"domain": "market", "asset": "Gold futures"},
    "SILVER": {"domain": "market", "asset": "Silver futures"},
    "CRUDE OIL": {"domain": "economic", "asset": "Crude Oil futures"},
    "NATURAL GAS": {"domain": "economic", "asset": "Natural Gas futures"},
    "E-MINI S&P 500": {"domain": "market", "asset": "S&P 500 E-mini futures"},
    "NASDAQ MINI": {"domain": "market", "asset": "NASDAQ mini futures"},
    "10-YEAR": {"domain": "economic", "asset": "10-Year Treasury futures"},
    "2-YEAR": {"domain": "economic", "asset": "2-Year Treasury futures"},
    "5-YEAR": {"domain": "economic", "asset": "5-Year Treasury futures"},
    "CORN": {"domain": "economic", "asset": "Corn futures"},
    "SOYBEANS": {"domain": "economic", "asset": "Soybean futures"},
    "WHEAT": {"domain": "economic", "asset": "Wheat futures"},
    "VIX": {"domain": "market", "asset": "VIX futures"},
    "BITCOIN": {"domain": "market", "asset": "Bitcoin futures"},
}


def _match_contract(market_name: str) -> Optional[tuple]:
    """Match a CFTC market name to our tracked contracts."""
    name_upper = market_name.upper()
    for key, info in KEY_CONTRACTS.items():
        if key in name_upper:
            return key, info
    return None


async def fetch_cftc_events(
    timeout: float = 60.0,
) -> List[Dict[str, Any]]:
    """
    Fetch latest CFTC Commitment of Traders data.
    Returns list of event dicts with positioning data.
    """
    events = []

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        try:
            logger.info("Fetching CFTC Commitment of Traders data...")
            resp = await client.get(CFTC_CURRENT_URL)
            resp.raise_for_status()

            content = resp.text
            reader = csv.DictReader(io.StringIO(content))

            for row in reader:
                try:
                    market_name = row.get("Market_and_Exchange_Names", "")
                    match = _match_contract(market_name)
                    if not match:
                        continue

                    contract_key, contract_info = match

                    # Extract positioning data
                    report_date = row.get("Report_Date_as_YYYY-MM-DD", "") or row.get("As_of_Date_In_Form_YYMMDD", "")

                    # Managed Money (hedge funds / large speculators)
                    mm_long = int(row.get("M_Money_Positions_Long_All", 0) or 0)
                    mm_short = int(row.get("M_Money_Positions_Short_All", 0) or 0)
                    mm_net = mm_long - mm_short

                    # Producer/Merchant (commercials)
                    prod_long = int(row.get("Prod_Merc_Positions_Long_All", 0) or 0)
                    prod_short = int(row.get("Prod_Merc_Positions_Short_All", 0) or 0)
                    prod_net = prod_long - prod_short

                    # Swap Dealers
                    swap_long = int(row.get("Swap_Positions_Long_All", 0) or 0)
                    swap_short = int(row.get("Swap__Positions_Short_All", 0) or 0)
                    swap_net = swap_long - swap_short

                    # Open Interest
                    open_interest = int(row.get("Open_Interest_All", 0) or 0)

                    # Change from previous week
                    mm_long_chg = int(row.get("Change_in_M_Money_Long_All", 0) or 0)
                    mm_short_chg = int(row.get("Change_in_M_Money_Short_All", 0) or 0)
                    mm_net_chg = mm_long_chg - mm_short_chg

                    # Determine positioning bias
                    if mm_net > 0:
                        bias = "net long (bullish)"
                    elif mm_net < 0:
                        bias = "net short (bearish)"
                    else:
                        bias = "neutral"

                    raw_text = (
                        f"CFTC Commitment of Traders: {contract_info['asset']} ({contract_key}). "
                        f"Managed Money: {bias}, net {mm_net:+,} contracts "
                        f"(change: {mm_net_chg:+,}). "
                        f"Open Interest: {open_interest:,}."
                    )

                    timestamp = datetime.utcnow()
                    if report_date:
                        try:
                            timestamp = datetime.strptime(report_date, "%Y-%m-%d")
                        except ValueError:
                            pass

                    # Severity based on magnitude of positioning change
                    severity = "routine"
                    if open_interest > 0:
                        chg_pct = abs(mm_net_chg) / open_interest * 100
                        if chg_pct > 5.0:
                            severity = "significant"
                        elif chg_pct > 2.0:
                            severity = "notable"

                    events.append({
                        "id": f"cftc-{contract_key}-{report_date}",
                        "source": "cftc",
                        "source_detail": "cftc.gov/dea/futures",
                        "timestamp": timestamp,
                        "domain": contract_info["domain"],
                        "event_type": "cot_report",
                        "severity": severity,
                        "entities": [
                            {"name": contract_info["asset"], "type": "instrument", "role": "subject"},
                            {"name": "CFTC", "type": "organization", "role": "source"},
                        ],
                        "raw_text": raw_text,
                        "metadata": {
                            "contract": contract_key,
                            "managed_money_net": mm_net,
                            "managed_money_net_change": mm_net_chg,
                            "managed_money_long": mm_long,
                            "managed_money_short": mm_short,
                            "producer_net": prod_net,
                            "swap_dealer_net": swap_net,
                            "open_interest": open_interest,
                            "report_date": report_date,
                            "bias": bias,
                        },
                    })
                except Exception as e:
                    logger.debug(f"Error parsing CFTC row: {e}")
                    continue

        except httpx.HTTPStatusError as e:
            logger.error(f"CFTC HTTP error: {e.response.status_code}")
        except httpx.TimeoutException:
            logger.warning("CFTC request timed out")
        except Exception as e:
            logger.error(f"CFTC fetch error: {e}")

    logger.info(f"CFTC: returning {len(events)} events")
    return events
