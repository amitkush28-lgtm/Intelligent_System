"""
Specialist agents — one per analytical domain.

All inherit from BaseAgent which provides the Cascading Consequences framework,
Prediction Quality Gates, and standard analysis cycle.
"""

from services.agents.specialists.economist import EconomistAgent
from services.agents.specialists.geopolitical import GeopoliticalAgent
from services.agents.specialists.investor import InvestorAgent
from services.agents.specialists.political import PoliticalAgent
from services.agents.specialists.sentiment import SentimentAgent
from services.agents.specialists.wildcard import WildCardAgent
from services.agents.specialists.master import MasterAgent

__all__ = [
    "EconomistAgent",
    "GeopoliticalAgent",
    "InvestorAgent",
    "PoliticalAgent",
    "SentimentAgent",
    "WildCardAgent",
    "MasterAgent",
]
