"""
Specialist agents for the multi-agent intelligence system.
"""

from services.agents.specialists.economist import EconomistAgent
from services.agents.specialists.geopolitical import GeopoliticalAgent
from services.agents.specialists.investor import InvestorAgent
from services.agents.specialists.political import PoliticalAgent
from services.agents.specialists.sentiment import SentimentAgent
from services.agents.specialists.master import MasterAgent

__all__ = [
    "EconomistAgent",
    "GeopoliticalAgent",
    "InvestorAgent",
    "PoliticalAgent",
    "SentimentAgent",
    "MasterAgent",
]

# Agent registry for dynamic lookup
AGENT_REGISTRY = {
    "economist": EconomistAgent,
    "geopolitical": GeopoliticalAgent,
    "investor": InvestorAgent,
    "political": PoliticalAgent,
    "sentiment": SentimentAgent,
    "master": MasterAgent,
}