"""
Reports API routes — thematic deep-dive reports and PDF export.

POST /reports/generate — Generate a thematic report on a specific domain
GET /reports/latest — Retrieve the latest generated report of a specific type
GET /reports/pdf — Export any report or newsletter as a professional PDF
"""

import io
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

from fastapi import APIRouter, Depends, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY

from fastapi.responses import JSONResponse

from shared.database import get_db, SessionLocal
from shared.models import Prediction, Event, WeakSignal, Debate, Note, ConfidenceTrail, Claim
from shared.config import get_settings
from shared.llm_client import call_claude_sonnet
from services.api.auth import verify_api_key

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/reports", tags=["reports"])

# Theme definitions and system prompts
THEMES = {
    "geopolitics_security": {
        "name": "Geopolitics & Security",
        "domains": ["geopolitical"],
        "system_prompt": """You are an expert geopolitical analyst writing a professional deep-dive report.
Your report should:
- Analyze current geopolitical flashpoints and security risks
- Evaluate state actor intentions and capabilities
- Assess alliance dynamics and shifting alignments
- Synthesize weak signals into emerging threat patterns
- Provide actionable strategic implications
- Be 2500-3500 words with clear thesis and supporting evidence
- Use precise language and cite specific dates/entities from the context provided
- Structure: Executive Summary, Key Developments, Threat Assessment, Scenarios, Implications"""
    },
    "economy_markets": {
        "name": "Economy & Markets",
        "domains": ["economic", "market"],
        "system_prompt": """You are an expert economist and market analyst writing a professional deep-dive report.
Your report should:
- Analyze macroeconomic trends and their implications
- Evaluate market dynamics (equities, commodities, currencies)
- Assess inflation, interest rates, and monetary policy shifts
- Synthesize weak signals into emerging economic patterns
- Connect predictions to current market conditions
- Be 2500-3500 words with clear thesis and supporting evidence
- Use precise numbers, dates, and specific asset prices/indices
- Structure: Executive Summary, Macro Overview, Market Assessment, Risk Factors, Outlook"""
    },
    "technology_ai": {
        "name": "Technology & AI",
        "domains": ["technology"],
        "system_prompt": """You are an expert technology and AI analyst writing a professional deep-dive report.
Your report should:
- Analyze recent breakthroughs and their implications
- Evaluate AI capability trajectories and risks
- Assess technological disruption patterns
- Synthesize weak signals into emerging tech trends
- Discuss competitive dynamics and market shifts
- Be 2500-3500 words with clear thesis and supporting evidence
- Reference specific technologies, companies, and milestones
- Structure: Executive Summary, Tech Landscape, AI Assessment, Disruption Patterns, Implications"""
    },
    "political_risk": {
        "name": "Political Risk",
        "domains": ["political"],
        "system_prompt": """You are an expert political risk analyst writing a professional deep-dive report.
Your report should:
- Analyze political instability risks and regime dynamics
- Evaluate electoral outcomes and policy implications
- Assess civil unrest potential and stability factors
- Synthesize weak signals into emerging political patterns
- Connect to business and investment implications
- Be 2500-3500 words with clear thesis and supporting evidence
- Reference specific countries, actors, and timeframes
- Structure: Executive Summary, Political Landscape, Risk Assessment, Scenarios, Business Impact"""
    },
    "energy_climate": {
        "name": "Energy & Climate",
        "domains": ["climate"],
        "system_prompt": """You are an expert energy and climate analyst writing a professional deep-dive report.
Your report should:
- Analyze energy transitions and supply dynamics
- Evaluate climate impacts on economies and geopolitics
- Assess renewable energy disruption patterns
- Synthesize weak signals into emerging climate trends
- Connect to financial and resource implications
- Be 2500-3500 words with clear thesis and supporting evidence
- Use specific data points, temperatures, energy units, and timelines
- Structure: Executive Summary, Energy Landscape, Climate Assessment, Transition Patterns, Implications"""
    },
    "trade_supply_chains": {
        "name": "Trade & Supply Chains",
        "domains": ["economic", "geopolitical"],
        "system_prompt": """You are an expert trade and supply chain analyst writing a professional deep-dive report.
Your report should:
- Analyze global trade patterns and disruption risks
- Evaluate supply chain vulnerabilities and reshoring trends
- Assess geopolitical trade dynamics and sanctions impact
- Synthesize weak signals into emerging trade patterns
- Connect to corporate resilience and competitiveness
- Be 2500-3500 words with clear thesis and supporting evidence
- Reference specific commodities, routes, and companies
- Structure: Executive Summary, Trade Landscape, Chain Vulnerabilities, Risk Factors, Strategic Implications"""
    },
    "twelve_month_outlook": {
        "name": "12-Month Outlook",
        "domains": [],  # Special case: uses all predictions
        "system_prompt": """You are a master strategic analyst synthesizing the highest-conviction predictions into a forward-looking narrative.
Your report should:
- Synthesize the system's top predictions by impact area
- Create a coherent narrative of the next 12 months
- Identify key decision points and inflection moments
- Assess interconnections between different impact areas
- Highlight highest-conviction claims (>75% confidence)
- Be 3000-4000 words with compelling narrative structure
- Use precise probability language and cite confidence levels
- Structure: Executive Summary, Lifestyle Implications, Financial Outlook, Safety Assessment, Political Shifts, Technology Trajectory, Key Dates & Decisions"""
    }
}

# In-memory store for latest reports by type
_latest_reports = {theme: {"content": None, "generated_at": None, "generating": False}
                    for theme in THEMES.keys()}


class ReportResponse(BaseModel):
    content: Optional[str] = None
    generated_at: Optional[str] = None
    type: str
    status: str = "empty"


class ReportRequest(BaseModel):
    theme: str = "geopolitics_security"


def _build_report_context(db: Session, theme: str) -> str:
    """Build context for report generation, filtered by theme domains."""
    parts = []
    theme_config = THEMES.get(theme, {})
    domains = theme_config.get("domains", [])

    if theme == "twelve_month_outlook":
        # Special case: get all active predictions sorted by confidence
        predictions = (
            db.query(Prediction)
            .filter(Prediction.status == "ACTIVE")
            .order_by(Prediction.current_confidence.desc())
            .all()
        )

        if predictions:
            parts.append("## HIGHEST-CONVICTION PREDICTIONS")

            # Group by impact area based on keywords in claim text
            by_area = {
                "lifestyle": [],
                "finances": [],
                "safety": [],
                "politics": [],
                "technology": [],
                "other": []
            }

            for p in predictions:
                claim_lower = p.claim.lower()
                if any(word in claim_lower for word in ["life", "health", "everyday", "personal", "society"]):
                    by_area["lifestyle"].append(p)
                elif any(word in claim_lower for word in ["money", "invest", "market", "price", "economic", "gdp", "inflation"]):
                    by_area["finances"].append(p)
                elif any(word in claim_lower for word in ["war", "conflict", "terror", "disaster", "death", "casualty", "crisis"]):
                    by_area["safety"].append(p)
                elif any(word in claim_lower for word in ["election", "govern", "law", "policy", "vote", "congress", "senate"]):
                    by_area["politics"].append(p)
                elif any(word in claim_lower for word in ["ai", "tech", "software", "digital", "algorithm", "compute"]):
                    by_area["technology"].append(p)
                else:
                    by_area["other"].append(p)

            # Format predictions by area
            for area, preds in by_area.items():
                if preds:
                    parts.append(f"\n### {area.upper()}")
                    for p in preds[:5]:  # Top 5 per area
                        parts.append(f"- [{p.agent}] {p.current_confidence:.0%}: {p.claim[:200]}")
                        trail = (
                            db.query(ConfidenceTrail)
                            .filter(ConfidenceTrail.prediction_id == p.id)
                            .order_by(ConfidenceTrail.date.asc())
                            .first()
                        )
                        if trail and trail.reasoning:
                            parts.append(f"  Reasoning: {trail.reasoning[:250]}")

        return "\n".join(parts)

    # Standard themed report context
    parts.append(f"## SYSTEM DATA FOR {theme_config.get('name', theme).upper()}")

    # Recent events in relevant domains
    cutoff = datetime.utcnow() - timedelta(days=30)
    events = (
        db.query(Event)
        .filter(
            Event.timestamp >= cutoff,
            Event.domain.in_(domains) if domains else True
        )
        .order_by(Event.timestamp.desc())
        .limit(40)
        .all()
    )

    if events:
        parts.append("\n## RECENT EVENTS")
        for e in events[:30]:
            severity_tag = f"[{e.severity.upper()}]" if e.severity else ""
            parts.append(f"- {severity_tag} {e.source}: {(e.raw_text or '')[:250]}")

    # Relevant active predictions
    predictions = (
        db.query(Prediction)
        .filter(Prediction.status == "ACTIVE")
        .order_by(Prediction.current_confidence.desc())
        .limit(40)
        .all()
    )

    if predictions:
        parts.append("\n## RELEVANT PREDICTIONS")
        for p in predictions[:20]:
            deadline = ""
            if p.time_condition_end:
                deadline = f" (deadline: {p.time_condition_end})"
            parts.append(f"- [{p.agent}] {p.current_confidence:.0%}{deadline}: {p.claim[:250]}")
            trail = (
                db.query(ConfidenceTrail)
                .filter(ConfidenceTrail.prediction_id == p.id)
                .order_by(ConfidenceTrail.date.asc())
                .first()
            )
            if trail and trail.reasoning:
                parts.append(f"  {trail.reasoning[:300]}")

    # Weak signals
    signals = (
        db.query(WeakSignal)
        .order_by(WeakSignal.detected_at.desc())
        .limit(15)
        .all()
    )

    if signals:
        parts.append("\n## WEAK SIGNALS")
        for s in signals:
            parts.append(f"- [{s.strength}] {s.signal[:250]}")

    # Key analyst notes
    notes = (
        db.query(Note)
        .filter(Note.type.in_(["key_signal", "counter_signal", "analysis"]))
        .order_by(Note.date.desc())
        .limit(15)
        .all()
    )

    if notes:
        parts.append("\n## KEY ANALYST NOTES")
        for n in notes:
            parts.append(f"- [{n.type}] {n.text[:250]}")

    return "\n".join(parts)


async def _generate_report(theme: str):
    """Generate a thematic report using Claude.

    Creates its own DB session because FastAPI background tasks
    run after the request's session is closed.
    """
    global _latest_reports

    if theme not in _latest_reports:
        logger.error(f"Invalid theme: {theme}")
        return

    _latest_reports[theme]["generating"] = True

    db = SessionLocal()
    try:
        context = _build_report_context(db, theme)
        theme_config = THEMES.get(theme, {})
        system_prompt = theme_config.get("system_prompt", "")

        user_message = f"""Generate a professional deep-dive report on {theme_config.get('name', theme)}.

SYSTEM DATA:
{context}

INSTRUCTIONS:
1. Write a comprehensive, analytical report following the structure in your system prompt
2. Lead with judgment and actionable insights, not just summary
3. Be specific: cite actual numbers, dates, entities, and sources from the data
4. Support all claims with evidence from the context provided
5. Use professional academic/business writing style
6. Maintain objectivity and acknowledge uncertainty where appropriate
7. End with clear implications and recommendations

Begin the report now:"""

        response = await call_claude_sonnet(
            system_prompt=system_prompt,
            user_message=user_message,
            max_tokens=12000,
            temperature=0.4,
        )

        _latest_reports[theme]["content"] = response
        _latest_reports[theme]["generated_at"] = datetime.utcnow().isoformat()
        _latest_reports[theme]["generating"] = False

        logger.info(f"Report '{theme}' generated: {len(response)} chars")

    except Exception as e:
        logger.error(f"Report generation for '{theme}' failed: {e}")
        _latest_reports[theme]["generating"] = False
        _latest_reports[theme]["content"] = f"Report generation failed: {str(e)[:200]}"
        _latest_reports[theme]["generated_at"] = datetime.utcnow().isoformat()
    finally:
        db.close()


@router.post("/generate", response_model=ReportResponse)
async def generate_report(
    request: ReportRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """Generate a new thematic report.

    Args:
        request: ReportRequest with theme field
        db: Database session
    """
    theme = request.theme
    if theme not in THEMES:
        return ReportResponse(type=theme, status="invalid_theme")

    if _latest_reports[theme]["generating"]:
        return ReportResponse(type=theme, status="generating")

    background_tasks.add_task(_generate_report, theme)

    return ReportResponse(
        type=theme,
        status="generating",
        generated_at=datetime.utcnow().isoformat(),
    )


@router.get("/latest", response_model=ReportResponse)
async def get_latest_report(
    type: str = Query("geopolitics_security"),
    _key: str = Depends(verify_api_key),
):
    """Get the most recently generated report of a specific type.

    Args:
        type: Report theme or newsletter cadence
    """
    if type in _latest_reports:
        report = _latest_reports[type]
        if report["generating"]:
            return ReportResponse(type=type, status="generating")
        if report["content"]:
            return ReportResponse(
                content=report["content"],
                generated_at=report["generated_at"],
                type=type,
                status="ready",
            )
    return ReportResponse(type=type, status="empty")


def _apply_inline_markdown(text: str) -> str:
    """Convert markdown bold/italic to reportlab XML tags."""
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)
    return text


def _parse_markdown_to_paragraphs(markdown_text: str, styles: Dict[str, Any]) -> List[Any]:
    """Parse markdown content into reportlab elements.

    Args:
        markdown_text: The markdown content to parse
        styles: Dict with keys 'body', 'h1', 'h2', 'h3'

    Handles: headings, bold, italic, bullet points, code blocks.
    """
    elements = []
    lines = markdown_text.split('\n')
    in_code_block = False
    current_bullets = []

    def flush_bullets():
        if current_bullets:
            bullet_text = '<br/>'.join(current_bullets)
            elements.append(Paragraph(bullet_text, styles['body']))
            elements.append(Spacer(1, 0.1 * inch))
            current_bullets.clear()

    for line in lines:
        stripped = line.strip()

        # Code blocks — skip content
        if stripped.startswith('```'):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        # Check if this is a bullet line
        is_bullet = stripped.startswith('- ') or stripped.startswith('* ')

        # Flush pending bullets before a non-bullet line
        if not is_bullet:
            flush_bullets()

        # Headings
        if line.startswith('# '):
            if elements:
                elements.append(Spacer(1, 0.2 * inch))
            elements.append(Paragraph(_apply_inline_markdown(line[2:].strip()), styles['h1']))
            elements.append(Spacer(1, 0.15 * inch))

        elif line.startswith('## '):
            if elements:
                elements.append(Spacer(1, 0.15 * inch))
            elements.append(Paragraph(_apply_inline_markdown(line[3:].strip()), styles['h2']))
            elements.append(Spacer(1, 0.1 * inch))

        elif line.startswith('### '):
            if elements:
                elements.append(Spacer(1, 0.1 * inch))
            elements.append(Paragraph(_apply_inline_markdown(line[4:].strip()), styles['h3']))
            elements.append(Spacer(1, 0.08 * inch))

        # Bullet points
        elif is_bullet:
            bullet_text = _apply_inline_markdown(stripped[2:].strip())
            current_bullets.append(f"\u2022 {bullet_text}")

        # Regular paragraphs
        elif stripped:
            text = _apply_inline_markdown(stripped)
            if text:
                elements.append(Paragraph(text, styles['body']))
                elements.append(Spacer(1, 0.1 * inch))

    # Flush any remaining bullets
    flush_bullets()
    return elements


def _generate_pdf(content: str, title: str, source_type: str) -> bytes:
    """Generate a professional PDF from markdown content using reportlab.

    Args:
        content: Markdown content to convert
        title: Report/newsletter title
        source_type: 'report' or 'newsletter'

    Returns:
        PDF as bytes
    """
    buffer = io.BytesIO()

    # Create document
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    # Build custom styles dict for use throughout
    base = getSampleStyleSheet()

    custom = {
        'body': ParagraphStyle(
            name='CustomBody',
            parent=base['Normal'],
            fontName='Helvetica',
            fontSize=11,
            leading=16,
            alignment=TA_JUSTIFY,
            textColor=colors.HexColor('#333333'),
        ),
        'h1': ParagraphStyle(
            name='CustomH1',
            parent=base['Heading1'],
            fontName='Helvetica-Bold',
            fontSize=24,
            leading=28,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#1a1a1a'),
            spaceAfter=12,
        ),
        'h2': ParagraphStyle(
            name='CustomH2',
            parent=base['Heading2'],
            fontName='Helvetica-Bold',
            fontSize=16,
            leading=20,
            textColor=colors.HexColor('#2a2a2a'),
            spaceAfter=8,
            spaceBefore=8,
        ),
        'h3': ParagraphStyle(
            name='CustomH3',
            parent=base['Heading3'],
            fontName='Helvetica-BoldOblique',
            fontSize=13,
            leading=16,
            textColor=colors.HexColor('#3a3a3a'),
            spaceAfter=6,
        ),
    }

    # Build story
    story = []

    # Title page
    story.append(Spacer(1, 1.5 * inch))
    story.append(Paragraph(title, custom['h1']))
    story.append(Spacer(1, 0.3 * inch))

    subtitle = "Professional Intelligence Report" if source_type == "report" else "Intelligence Newsletter"
    story.append(Paragraph(subtitle, custom['h2']))
    story.append(Spacer(1, 0.2 * inch))

    timestamp = datetime.utcnow().strftime("%B %d, %Y")
    story.append(Paragraph(f"Generated: {timestamp}", custom['body']))
    story.append(PageBreak())

    # Parse and add content
    parsed_elements = _parse_markdown_to_paragraphs(content, custom)
    story.extend(parsed_elements)

    # Build PDF
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


@router.get("/pdf")
async def export_pdf(
    type: str = Query("geopolitics_security"),
    source: str = Query("report", description="'report' for themed reports or 'newsletter' for newsletter cadences"),
    _key: str = Depends(verify_api_key),
):
    """Export a report or newsletter as a professional PDF.

    Args:
        type: Report theme or newsletter cadence
        source: 'report' or 'newsletter'

    Returns:
        PDF file as downloadable attachment
    """
    content = None
    title = None

    # Check if it's a report
    if source == "report" and type in _latest_reports:
        if _latest_reports[type]["content"]:
            content = _latest_reports[type]["content"]
            title = THEMES.get(type, {}).get("name", type.replace("_", " ").title())
        else:
            return JSONResponse(status_code=404, content={"error": f"No report generated for type '{type}'"})

    # Check if it's a newsletter (look in newsletter store if available)
    elif source == "newsletter":
        try:
            from services.api.routes.newsletter import _latest_newsletters
            if type in _latest_newsletters and _latest_newsletters[type]["content"]:
                content = _latest_newsletters[type]["content"]
                title = f"{type.capitalize()} Intelligence Newsletter"
            else:
                return JSONResponse(status_code=404, content={"error": f"No newsletter generated for cadence '{type}'"})
        except ImportError:
            return JSONResponse(status_code=500, content={"error": "Newsletter module not available"})
    else:
        return JSONResponse(status_code=400, content={"error": f"Invalid source '{source}' or type '{type}'"})

    if not content:
        return JSONResponse(status_code=404, content={"error": "No content available to export"})

    # Generate PDF
    try:
        pdf_bytes = _generate_pdf(content, title, source)

        filename = f"{type}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        return JSONResponse(status_code=500, content={"error": f"PDF generation failed: {str(e)[:200]}"})
