"""
Daily Scheduler — Runs the full intelligence pipeline at 5 AM daily.

Pipeline order:
1. Data ingestion (all 14 sources)
2. Agent analysis (5 specialists + reality check + devil's advocate + master)
3. Feedback cycle (scoring + auto-resolution)
4. Weak signal scan
5. Generate newsletter
6. Convert to PDF and email

Deployed as a separate Railway service.
Uses APScheduler for cron-like scheduling.
"""

import asyncio
import logging
import os
import smtplib
import traceback
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from typing import Optional

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from shared.config import get_settings
from shared.utils import setup_logging

logger = setup_logging("scheduler")
settings = get_settings()


async def _run_full_pipeline():
    logger.info("=" * 60)
    logger.info("DAILY PIPELINE STARTING")
    logger.info(f"Timestamp: {datetime.utcnow().isoformat()}")
    logger.info("=" * 60)

    logger.info("STEP 1/7: Running data ingestion...")
    try:
        from services.ingestion.main import run_async as run_ingestion
        await run_ingestion()
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")

    await asyncio.sleep(5)

    logger.info("STEP 2/7: Running Living Questions daily monitoring...")
    try:
        from services.agents.question_monitor import run_daily_monitoring
        monitor_stats = await run_daily_monitoring()
        logger.info(
            f"Question monitor: {monitor_stats.get('evidence_logged', 0)} evidence logged, "
            f"{monitor_stats.get('status_changes', 0)} status changes"
        )
    except Exception as e:
        logger.error(f"Question monitoring failed: {e}")

    logger.info("STEP 3/7: Running agent analysis...")
    try:
        from services.agents.main import run_analysis_cycle
        stats = await run_analysis_cycle()
        logger.info(f"Agents complete: {stats.get('predictions_created', 0)} new predictions")
    except Exception as e:
        logger.error(f"Agent analysis failed: {e}")

    logger.info("STEP 4/7: Running feedback cycle...")
    try:
        from services.feedback.scorer import run_scoring_cycle
        run_scoring_cycle()
        from services.feedback.auto_resolver import run_auto_resolution
        await run_auto_resolution()
    except Exception as e:
        logger.error(f"Feedback failed: {e}")

    logger.info("STEP 5/7: Running weak signal scan...")
    try:
        from services.signals.main import run_async as run_signals
        await run_signals()
    except Exception as e:
        logger.error(f"Signals failed: {e}")

    logger.info("STEP 6/7: Generating newsletter...")
    try:
        newsletter_md = await _generate_newsletter()
        if newsletter_md:
            pdf_path = _convert_to_pdf(newsletter_md)
            if pdf_path:
                _send_email(pdf_path, newsletter_md)
    except Exception as e:
        logger.error(f"Newsletter failed: {e}")

    # Weekly trend tracker — runs on Sundays only
    if datetime.utcnow().weekday() == 6:  # Sunday
        logger.info("STEP 7/7: Running weekly Trend Tracker...")
        try:
            from services.agents.trend_tracker import run_weekly_trend_analysis
            trend_stats = await run_weekly_trend_analysis()
            logger.info(
                f"Trend Tracker: {trend_stats.get('variables_analyzed', 0)} variables analyzed, "
                f"accelerating: {trend_stats.get('accelerating', [])}"
            )
        except Exception as e:
            logger.error(f"Trend Tracker failed: {e}")
    else:
        logger.info("STEP 7/7: Trend Tracker skipped (runs Sundays only)")

    logger.info("=" * 60)
    logger.info("DAILY PIPELINE COMPLETE")
    logger.info("=" * 60)


async def _generate_newsletter():
    from shared.llm_client import call_claude_sonnet
    from shared.database import get_db_session
    from shared.models import Prediction, Event, ConfidenceTrail
    from datetime import timedelta

    SYSTEM = """You are the Master Strategist writing a daily intelligence newsletter.
Write like a senior analyst producing a morning briefing for policymakers.

# Intelligence Brief — [Today's Date]
## Executive Summary (2-3 sentences)
## Key Developments (3-5 themes, 2-4 paragraphs each)
## Active Predictions (grouped by domain with confidence levels)
## Convergence Alerts
## Contrarian Corner
## What We're Watching (next 7 days)

Write in markdown. Be specific, cite data, make bold calls."""

    try:
        with get_db_session() as db:
            cutoff = datetime.utcnow() - timedelta(hours=24)
            parts = []

            events = db.query(Event).filter(Event.timestamp >= cutoff).order_by(Event.timestamp.desc()).limit(50).all()
            if events:
                parts.append("## RECENT EVENTS")
                for e in events[:30]:
                    parts.append(f"- [{e.domain}] {e.source}: {(e.raw_text or '')[:200]}")

            predictions = db.query(Prediction).filter(Prediction.status == "ACTIVE").order_by(Prediction.current_confidence.desc()).limit(30).all()
            if predictions:
                parts.append("\n## ACTIVE PREDICTIONS")
                for p in predictions:
                    parts.append(f"- [{p.agent}] {p.current_confidence:.0%}: {p.claim}")
                    trail = db.query(ConfidenceTrail).filter(ConfidenceTrail.prediction_id == p.id).order_by(ConfidenceTrail.date.asc()).first()
                    if trail and trail.reasoning:
                        parts.append(f"  Reasoning: {trail.reasoning[:300]}")

            today = datetime.utcnow().strftime("%B %d, %Y")
            response = await call_claude_sonnet(
                system_prompt=SYSTEM,
                user_message=f"Today is {today}. Generate the newsletter:\n\n{chr(10).join(parts)}",
                max_tokens=8192,
                temperature=0.4,
            )
            logger.info(f"Newsletter generated: {len(response)} chars")
            return response
    except Exception as e:
        logger.error(f"Newsletter generation failed: {e}")
        return None


def _convert_to_pdf(markdown_text):
    try:
        import re
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib.colors import HexColor
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        pdf_path = f"/tmp/intelligence-brief-{today_str}.pdf"

        doc = SimpleDocTemplate(pdf_path, pagesize=letter, topMargin=0.75*inch, bottomMargin=0.75*inch, leftMargin=0.75*inch, rightMargin=0.75*inch)
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle("Title2", parent=styles["Heading1"], fontSize=20, spaceAfter=12, textColor=HexColor("#1a1a2e"))
        h2_style = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=14, spaceBefore=16, spaceAfter=8, textColor=HexColor("#16213e"))
        h3_style = ParagraphStyle("H3", parent=styles["Heading3"], fontSize=12, spaceBefore=12, spaceAfter=6, textColor=HexColor("#0f3460"))
        body_style = ParagraphStyle("Body2", parent=styles["Normal"], fontSize=10, leading=14, spaceAfter=8, textColor=HexColor("#333333"))
        bullet_style = ParagraphStyle("Bullet2", parent=body_style, leftIndent=20, bulletIndent=10)

        elements = []
        for line in markdown_text.split("\n"):
            line = line.strip()
            if not line:
                elements.append(Spacer(1, 6))
                continue
            safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            safe = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', safe)
            safe = re.sub(r'\*(.+?)\*', r'<i>\1</i>', safe)

            if line.startswith("# "):
                elements.append(Paragraph(safe[2:], title_style))
            elif line.startswith("## "):
                elements.append(Paragraph(safe[3:], h2_style))
            elif line.startswith("### "):
                elements.append(Paragraph(safe[4:], h3_style))
            elif line.startswith("- "):
                elements.append(Paragraph(f"&bull; {safe[2:]}", bullet_style))
            else:
                elements.append(Paragraph(safe, body_style))

        doc.build(elements)
        logger.info(f"PDF generated: {pdf_path}")
        return pdf_path
    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        return None


def _send_email(pdf_path, markdown_text):
    smtp_host = os.environ.get("SMTP_HOST", "")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    email_from = os.environ.get("NEWSLETTER_FROM", smtp_user)
    email_to = os.environ.get("NEWSLETTER_TO", "")

    if not all([smtp_host, smtp_user, smtp_password, email_to]):
        logger.warning("Email not configured. Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD, NEWSLETTER_TO.")
        return

    try:
        today_str = datetime.utcnow().strftime("%B %d, %Y")
        msg = MIMEMultipart()
        msg["From"] = email_from
        msg["To"] = email_to
        msg["Subject"] = f"Intelligence Brief - {today_str}"

        summary = markdown_text[:500].replace("#", "").replace("*", "")
        msg.attach(MIMEText(f"Daily Intelligence Brief - {today_str}\n\n{summary}\n\n[Full newsletter attached as PDF]", "plain"))

        with open(pdf_path, "rb") as f:
            part = MIMEBase("application", "pdf")
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="intelligence-brief-{datetime.utcnow().strftime("%Y-%m-%d")}.pdf"')
            msg.attach(part)

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)

        logger.info(f"Newsletter emailed to {email_to}")
    except Exception as e:
        logger.error(f"Email delivery failed: {e}")


def _run_pipeline_sync():
    asyncio.run(_run_full_pipeline())


def main():
    schedule_hour = int(os.environ.get("SCHEDULE_HOUR", "5"))
    schedule_minute = int(os.environ.get("SCHEDULE_MINUTE", "0"))
    timezone = os.environ.get("SCHEDULE_TIMEZONE", "UTC")

    logger.info(f"Scheduler starting - pipeline runs daily at {schedule_hour:02d}:{schedule_minute:02d} {timezone}")

    scheduler = BlockingScheduler()
    scheduler.add_job(
        _run_pipeline_sync,
        CronTrigger(hour=schedule_hour, minute=schedule_minute, timezone=timezone),
        id="daily_pipeline",
        name="Daily Intelligence Pipeline",
        misfire_grace_time=3600,
    )

    if os.environ.get("IMMEDIATE_RUN", "").lower() == "true":
        logger.info("IMMEDIATE_RUN=true - running pipeline now")
        _run_pipeline_sync()

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler shutting down")


if __name__ == "__main__":
    main()
