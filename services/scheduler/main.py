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

    logger.info("STEP 1/8: Running data ingestion (21 sources)...")
    try:
        from services.ingestion.main import run_async as run_ingestion
        await run_ingestion()
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")

    await asyncio.sleep(5)

    logger.info("STEP 2/8: Running Living Questions daily monitoring...")
    try:
        from services.agents.question_monitor import run_daily_monitoring
        monitor_stats = await run_daily_monitoring()
        logger.info(
            f"Question monitor: {monitor_stats.get('evidence_logged', 0)} evidence logged, "
            f"{monitor_stats.get('status_changes', 0)} status changes"
        )
    except Exception as e:
        logger.error(f"Question monitoring failed: {e}")

    logger.info("STEP 3/8: Running agent analysis...")
    try:
        from services.agents.main import run_analysis_cycle
        stats = await run_analysis_cycle()
        logger.info(f"Agents complete: {stats.get('predictions_created', 0)} new predictions")
    except Exception as e:
        logger.error(f"Agent analysis failed: {e}")

    logger.info("STEP 4/8: Running feedback cycle...")
    try:
        from services.feedback.scorer import run_scoring_cycle
        run_scoring_cycle()
        from services.feedback.auto_resolver import run_auto_resolution
        await run_auto_resolution()
    except Exception as e:
        logger.error(f"Feedback failed: {e}")

    logger.info("STEP 5/8: Running Verification Engine (cross-modal claim verification)...")
    try:
        from services.verification.main import run_async as run_verification
        verif_stats = await run_verification()
        q_stats = verif_stats.get("queue_stats", {})
        r_stats = verif_stats.get("recheck_stats", {})
        logger.info(
            f"Verification: {q_stats.get('claims_processed', 0)} claims verified, "
            f"{q_stats.get('corroborations_total', 0)} corroborations, "
            f"{q_stats.get('contradictions_total', 0)} contradictions, "
            f"{r_stats.get('updated', 0)} unverified claims re-checked"
        )
    except Exception as e:
        logger.error(f"Verification Engine failed: {e}")
        logger.debug(traceback.format_exc())

    logger.info("STEP 6/8: Running weak signal scan...")
    try:
        from services.signals.main import run_async as run_signals
        await run_signals()
    except Exception as e:
        logger.error(f"Signals failed: {e}")

    logger.info("STEP 7/8: Generating daily newsletter...")
    try:
        newsletter_md = await _generate_newsletter(cadence="daily")
        if newsletter_md:
            pdf_path = _convert_to_pdf(newsletter_md, cadence="daily")
            if pdf_path:
                _send_email(pdf_path, newsletter_md, cadence="daily")
    except Exception as e:
        logger.error(f"Daily newsletter failed: {e}")

    # Weekly newsletter (Sundays)
    if datetime.utcnow().weekday() == 6:  # Sunday
        logger.info("Generating weekly newsletter...")
        try:
            weekly_md = await _generate_newsletter(cadence="weekly")
            if weekly_md:
                pdf_path = _convert_to_pdf(weekly_md, cadence="weekly")
                if pdf_path:
                    _send_email(pdf_path, weekly_md, cadence="weekly")
        except Exception as e:
            logger.error(f"Weekly newsletter failed: {e}")

    # Monthly newsletter (1st of month)
    if datetime.utcnow().day == 1:
        logger.info("Generating monthly newsletter...")
        try:
            monthly_md = await _generate_newsletter(cadence="monthly")
            if monthly_md:
                pdf_path = _convert_to_pdf(monthly_md, cadence="monthly")
                if pdf_path:
                    _send_email(pdf_path, monthly_md, cadence="monthly")
        except Exception as e:
            logger.error(f"Monthly newsletter failed: {e}")

    # Yearly newsletter (January 1st)
    if datetime.utcnow().month == 1 and datetime.utcnow().day == 1:
        logger.info("Generating yearly newsletter...")
        try:
            yearly_md = await _generate_newsletter(cadence="yearly")
            if yearly_md:
                pdf_path = _convert_to_pdf(yearly_md, cadence="yearly")
                if pdf_path:
                    _send_email(pdf_path, yearly_md, cadence="yearly")
        except Exception as e:
            logger.error(f"Yearly newsletter failed: {e}")

    # Weekly trend tracker — runs on Sundays only
    if datetime.utcnow().weekday() == 6:  # Sunday
        logger.info("STEP 8/8: Running weekly Trend Tracker...")
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
        logger.info("STEP 8/8: Trend Tracker skipped (runs Sundays only)")

    logger.info("=" * 60)
    logger.info("DAILY PIPELINE COMPLETE")
    logger.info("=" * 60)


async def _generate_newsletter(cadence: str = "daily"):
    """Generate a newsletter of a specific cadence.

    Args:
        cadence: One of 'daily', 'weekly', 'monthly', 'yearly'
    """
    from shared.llm_client import call_claude_sonnet
    from shared.database import get_db_session
    from shared.models import Prediction, Event, ConfidenceTrail, WeakSignal, Debate, Note
    from shared.newsletter_prompts import (
        DAILY_SYSTEM_PROMPT,
        WEEKLY_SYSTEM_PROMPT,
        MONTHLY_SYSTEM_PROMPT,
        YEARLY_SYSTEM_PROMPT,
    )
    from datetime import timedelta

    try:
        with get_db_session() as db:
            # Determine lookback windows based on cadence
            if cadence == "daily":
                event_lookback = timedelta(hours=24)
                recent_lookback = timedelta(days=7)
                scorecard_window = timedelta(days=30)
                system_prompt = DAILY_SYSTEM_PROMPT
                read_limit = "8-12"
            elif cadence == "weekly":
                event_lookback = timedelta(days=7)
                recent_lookback = timedelta(days=14)
                scorecard_window = timedelta(days=30)
                system_prompt = WEEKLY_SYSTEM_PROMPT
                read_limit = "15-20"
            elif cadence == "monthly":
                event_lookback = timedelta(days=30)
                recent_lookback = timedelta(days=30)
                scorecard_window = timedelta(days=30)
                system_prompt = MONTHLY_SYSTEM_PROMPT
                read_limit = "25-30"
            elif cadence == "yearly":
                event_lookback = timedelta(days=365)
                recent_lookback = timedelta(days=365)
                scorecard_window = timedelta(days=365)
                system_prompt = YEARLY_SYSTEM_PROMPT
                read_limit = "45-60"
            else:
                cadence = "daily"
                event_lookback = timedelta(hours=24)
                recent_lookback = timedelta(days=7)
                scorecard_window = timedelta(days=30)
                system_prompt = DAILY_SYSTEM_PROMPT
                read_limit = "8-12"

            parts = []
            parts.append("## SYSTEM SCORECARD DATA")

            # --- Track record data ---
            scorecard_cutoff = datetime.utcnow() - scorecard_window
            resolved = (
                db.query(Prediction)
                .filter(
                    Prediction.status.in_(["RESOLVED_TRUE", "RESOLVED_FALSE"]),
                    Prediction.resolved_date >= scorecard_cutoff.date(),
                )
                .all()
            )
            correct = sum(1 for p in resolved if p.status == "RESOLVED_TRUE")
            total_resolved = len(resolved)
            hit_rate = (correct / total_resolved * 100) if total_resolved > 0 else 0
            brier_scores = [p.brier_score for p in resolved if p.brier_score is not None]
            avg_brier = sum(brier_scores) / len(brier_scores) if brier_scores else None
            parts.append(f"Predictions resolved ({scorecard_window.days} days): {total_resolved}")
            parts.append(f"Correct: {correct} ({hit_rate:.0f}%)")
            parts.append(f"Average Brier Score: {avg_brier:.3f}" if avg_brier else "Brier Score: Not yet available")

            # Recently resolved
            recent_cutoff = datetime.utcnow() - recent_lookback
            recently_resolved = (
                db.query(Prediction)
                .filter(
                    Prediction.status.in_(["RESOLVED_TRUE", "RESOLVED_FALSE"]),
                    Prediction.resolved_date >= recent_cutoff.date(),
                )
                .order_by(Prediction.resolved_date.desc())
                .limit(20)
                .all()
            )
            if recently_resolved:
                parts.append(f"\nRecently Resolved ({recent_lookback.days}d window):")
                for p in recently_resolved:
                    outcome = "TRUE" if p.status == "RESOLVED_TRUE" else "FALSE"
                    brier = f" (Brier: {p.brier_score:.2f})" if p.brier_score else ""
                    parts.append(f"  {outcome} [{p.agent}] {p.current_confidence:.0%}: {p.claim[:150]}{brier}")

            # --- Recent events ---
            event_cutoff = datetime.utcnow() - event_lookback
            events = db.query(Event).filter(Event.timestamp >= event_cutoff).order_by(Event.timestamp.desc()).limit(50).all()
            event_label = f"{event_lookback.days}d" if event_lookback.days > 0 else "24h"
            if events:
                parts.append(f"\n## RECENT EVENTS (last {event_label})")
                for e in events[:40]:
                    severity_tag = f"[{e.severity.upper()}]" if e.severity else ""
                    parts.append(f"- {severity_tag} [{e.domain}] {e.source}: {(e.raw_text or '')[:250]}")

            # --- Active predictions ---
            predictions = (
                db.query(Prediction)
                .filter(Prediction.status == "ACTIVE")
                .order_by(Prediction.current_confidence.desc())
                .limit(30)
                .all()
            )
            if predictions:
                parts.append("\n## ACTIVE PREDICTIONS")
                for p in predictions:
                    deadline = f" (deadline: {p.time_condition_end})" if p.time_condition_end else ""
                    parts.append(f"- [{p.agent}] {p.current_confidence:.0%}{deadline}: {p.claim[:200]}")
                    trail = (
                        db.query(ConfidenceTrail)
                        .filter(ConfidenceTrail.prediction_id == p.id)
                        .order_by(ConfidenceTrail.date.asc())
                        .first()
                    )
                    if trail and trail.reasoning:
                        parts.append(f"  Reasoning: {trail.reasoning[:300]}")

            # --- High-conviction predictions ---
            high_conv = [p for p in (predictions or []) if p.current_confidence >= 0.70]
            if high_conv:
                parts.append("\n## HIGH-CONVICTION PREDICTIONS (>70%)")
                for p in high_conv[:10]:
                    parts.append(f"- [{p.agent}] {p.current_confidence:.0%}: {p.claim[:200]}")

            # --- Devil's Advocate debates ---
            debates = db.query(Debate).order_by(Debate.created_at.desc()).limit(5).all()
            if debates:
                parts.append("\n## RECENT DEVIL'S ADVOCATE DEBATES")
                for d in debates:
                    parts.append(f"- [{d.agent}] Trigger: {d.trigger_reason}")
                    if d.rounds and isinstance(d.rounds, list):
                        for r in d.rounds[:1]:
                            if isinstance(r, dict) and r.get("devil") and isinstance(r["devil"], dict):
                                parts.append(f"  Assessment: {r['devil'].get('overall_assessment', '')[:200]}")
                                parts.append(f"  Strongest weakness: {r['devil'].get('strongest_weakness', '')[:200]}")

            # --- Weak signals ---
            signals = db.query(WeakSignal).order_by(WeakSignal.detected_at.desc()).limit(10).all()
            if signals:
                parts.append("\n## WEAK SIGNALS")
                for s in signals:
                    parts.append(f"- [{s.strength}] {s.signal[:200]}")

            # --- Living Questions summary ---
            try:
                from shared.models import LivingQuestion
                active_questions = (
                    db.query(LivingQuestion)
                    .filter(LivingQuestion.status == "active")
                    .order_by(LivingQuestion.last_analyzed_at.desc())
                    .limit(5)
                    .all()
                )
                if active_questions:
                    parts.append("\n## ACTIVE LIVING QUESTIONS")
                    for q in active_questions:
                        verdict = q.thesis_verdict or "PENDING"
                        conf = f"{q.overall_confidence}%" if q.overall_confidence else "?"
                        parts.append(f"- [{verdict} {conf}] {q.question[:150]}")
                        if q.thesis_summary:
                            parts.append(f"  {q.thesis_summary[:200]}")
            except Exception:
                pass

            # Generate the newsletter
            today = datetime.utcnow().strftime("%B %d, %Y")
            context = "\n".join(parts)

            cadence_instruction = {
                "daily": "Generate the daily intelligence newsletter.",
                "weekly": "Generate the weekly intelligence newsletter.",
                "monthly": "Generate the monthly strategic intelligence newsletter.",
                "yearly": "Generate the annual intelligence review and outlook.",
            }.get(cadence, "Generate the daily intelligence newsletter.")

            response = await call_claude_sonnet(
                system_prompt=system_prompt,
                user_message=f"""Today is {today}. {cadence_instruction}

SYSTEM STATE:
{context}

INSTRUCTIONS:
1. Follow the newsletter structure EXACTLY as specified in your system prompt.
2. Lead with JUDGMENT, not summary.
3. Every argumentative section must have a thesis and end with actionable guidance.
4. Include the Track Record scorecard using the data provided.
5. Use the Devil's Advocate debate material for contrarian sections.
6. Include Living Questions insights where relevant.
7. Be SPECIFIC — cite actual numbers, dates, prices, entities.
8. Respect the {read_limit} minute read limit.

Write the complete newsletter in markdown.""",
                max_tokens=12000,
                temperature=0.4,
            )
            logger.info(f"{cadence.upper()} newsletter generated: {len(response)} chars")
            return response
    except Exception as e:
        logger.error(f"{cadence.upper()} newsletter generation failed: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return None


def _convert_to_pdf(markdown_text, cadence: str = "daily"):
    """Convert newsletter markdown to a professionally formatted PDF.

    Args:
        markdown_text: The newsletter markdown content
        cadence: Newsletter cadence (daily, weekly, monthly, yearly)
    """
    try:
        import re
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib.colors import HexColor, Color
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            HRFlowable, KeepTogether,
        )

        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        today_display = datetime.utcnow().strftime("%B %d, %Y")

        # Include cadence in filename
        cadence_prefix = f"{cadence.lower()}-"
        pdf_path = f"/tmp/{cadence_prefix}intelligence-brief-{today_str}.pdf"

        # -- Color palette --
        NAVY = HexColor("#0f172a")
        DARK_BLUE = HexColor("#1e293b")
        MED_BLUE = HexColor("#334155")
        ACCENT_BLUE = HexColor("#3b82f6")
        LIGHT_TEXT = HexColor("#475569")
        BODY_TEXT = HexColor("#1e293b")
        RED = HexColor("#ef4444")
        GREEN = HexColor("#10b981")
        AMBER = HexColor("#f59e0b")
        SECTION_BG = HexColor("#f8fafc")

        # Section accent colors for the left-border stripe
        SECTION_COLORS = {
            "TRACK RECORD": HexColor("#3b82f6"),
            "THE ONE THING": HexColor("#ef4444"),
            "KEY DEVELOPMENTS": HexColor("#8b5cf6"),
            "CONVERGENCE": HexColor("#ef4444"),
            "NEW PREDICTIONS": HexColor("#10b981"),
            "PREDICTION SCORECARD": HexColor("#f59e0b"),
            "CONTRARIAN CORNER": HexColor("#ec4899"),
            "WHAT WE": HexColor("#6366f1"),
            "PORTFOLIO": HexColor("#14b8a6"),
            "TRAVEL": HexColor("#f97316"),
        }

        def _get_section_color(heading_text):
            upper = heading_text.upper()
            for key, color in SECTION_COLORS.items():
                if key in upper:
                    return color
            return ACCENT_BLUE

        # -- Document setup --
        doc = SimpleDocTemplate(
            pdf_path, pagesize=letter,
            topMargin=0.6 * inch, bottomMargin=0.6 * inch,
            leftMargin=0.7 * inch, rightMargin=0.7 * inch,
        )

        styles = getSampleStyleSheet()

        # -- Custom styles --
        title_style = ParagraphStyle(
            "BriefTitle", parent=styles["Heading1"],
            fontSize=22, leading=26, spaceAfter=4,
            textColor=NAVY, fontName="Helvetica-Bold",
        )
        date_style = ParagraphStyle(
            "BriefDate", parent=styles["Normal"],
            fontSize=10, textColor=LIGHT_TEXT, spaceAfter=16,
            fontName="Helvetica",
        )
        h2_style = ParagraphStyle(
            "SectionH2", parent=styles["Heading2"],
            fontSize=13, leading=16, spaceBefore=6, spaceAfter=8,
            textColor=NAVY, fontName="Helvetica-Bold",
        )
        h3_style = ParagraphStyle(
            "SubH3", parent=styles["Heading3"],
            fontSize=11, leading=14, spaceBefore=10, spaceAfter=6,
            textColor=DARK_BLUE, fontName="Helvetica-Bold",
        )
        body_style = ParagraphStyle(
            "BriefBody", parent=styles["Normal"],
            fontSize=9.5, leading=13.5, spaceAfter=6,
            textColor=BODY_TEXT, fontName="Helvetica",
        )
        bullet_style = ParagraphStyle(
            "BriefBullet", parent=body_style,
            leftIndent=18, bulletIndent=8, spaceAfter=4,
        )
        callout_style = ParagraphStyle(
            "Callout", parent=body_style,
            fontSize=9.5, leading=13, leftIndent=12,
            textColor=HexColor("#1d4ed8"), fontName="Helvetica-BoldOblique",
            spaceAfter=8,
        )
        hr_color = HexColor("#e2e8f0")

        def make_safe(line):
            """Escape HTML entities and convert markdown inline formatting."""
            safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            safe = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', safe)
            safe = re.sub(r'\*(.+?)\*', r'<i>\1</i>', safe)
            safe = re.sub(r'`(.+?)`', r'<font face="Courier" size="8">\1</font>', safe)
            # Prediction markers
            safe = safe.replace("&amp;#10003;", "<font color='#10b981'>&#10003;</font>")
            safe = safe.replace("&amp;#10007;", "<font color='#ef4444'>&#10007;</font>")
            return safe

        def section_divider(color=None):
            """Colored horizontal rule between sections."""
            return HRFlowable(
                width="100%", thickness=1.5,
                color=color or hr_color,
                spaceAfter=10, spaceBefore=10,
            )

        def section_header_block(text, accent_color):
            """Section header with colored left accent bar."""
            stripped = re.sub(r'^[\s#]+', '', text).strip()
            # Remove leading emojis (they don't render in ReportLab)
            stripped = re.sub(r'^[\U0001F300-\U0001F9FF\u2600-\u27FF\u2702-\u27B0]+\s*', '', stripped)
            safe = make_safe(stripped)

            header_para = Paragraph(safe, h2_style)

            # Create a table with colored left border
            t = Table(
                [[header_para]],
                colWidths=[doc.width],
                rowHeights=[None],
            )
            t.setStyle(TableStyle([
                ('LEFTPADDING', (0, 0), (-1, -1), 10),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('LINEBEFORENEW', (0, 0), (0, -1), 3, accent_color),
                ('BACKGROUND', (0, 0), (-1, -1), SECTION_BG),
            ]))
            return t

        # -- Parse and build --
        elements = []
        lines = markdown_text.split("\n")
        i = 0
        in_paragraph = []

        def flush_paragraph():
            """Flush accumulated paragraph lines into a single body paragraph."""
            nonlocal in_paragraph
            if in_paragraph:
                combined = " ".join(in_paragraph)
                elements.append(Paragraph(make_safe(combined), body_style))
                in_paragraph = []

        while i < len(lines):
            line = lines[i].rstrip()
            stripped = line.strip()

            # Skip the --- dividers
            if stripped == "---":
                flush_paragraph()
                elements.append(section_divider())
                i += 1
                continue

            # Empty line — paragraph break
            if not stripped:
                flush_paragraph()
                i += 1
                continue

            # Title (# heading)
            if stripped.startswith("# ") and not stripped.startswith("## "):
                flush_paragraph()
                title_text = re.sub(r'^[\U0001F300-\U0001F9FF\u2600-\u27FF\u2702-\u27B0]+\s*', '', stripped[2:].strip())
                elements.append(Paragraph(make_safe(title_text), title_style))
                elements.append(Paragraph(today_display, date_style))
                elements.append(section_divider(ACCENT_BLUE))
                i += 1
                continue

            # Section heading (## heading)
            if stripped.startswith("## "):
                flush_paragraph()
                accent = _get_section_color(stripped)
                elements.append(Spacer(1, 8))
                elements.append(section_header_block(stripped, accent))
                elements.append(Spacer(1, 4))
                i += 1
                continue

            # Sub-heading (### heading)
            if stripped.startswith("### "):
                flush_paragraph()
                h3_text = stripped[4:].strip()
                h3_text = re.sub(r'^[\U0001F300-\U0001F9FF\u2600-\u27FF\u2702-\u27B0]+\s*', '', h3_text)
                elements.append(Paragraph(make_safe(h3_text), h3_style))
                i += 1
                continue

            # Callout line (> **WHAT TO DO:** ...)
            if stripped.startswith(">") or stripped.startswith("→"):
                flush_paragraph()
                callout_text = stripped.lstrip(">→ ").strip()
                elements.append(Paragraph(make_safe(callout_text), callout_style))
                i += 1
                continue

            # Bullet point
            if stripped.startswith("- ") or stripped.startswith("* "):
                flush_paragraph()
                bullet_text = stripped[2:].strip()
                elements.append(Paragraph(f"\u2022 {make_safe(bullet_text)}", bullet_style))
                i += 1
                continue

            # Numbered list
            if re.match(r'^\d+\.\s', stripped):
                flush_paragraph()
                elements.append(Paragraph(make_safe(stripped), bullet_style))
                i += 1
                continue

            # Regular text — accumulate into paragraph
            in_paragraph.append(stripped)
            i += 1

        flush_paragraph()

        # Footer with cadence
        elements.append(Spacer(1, 20))
        elements.append(section_divider(LIGHT_TEXT))
        footer_style = ParagraphStyle(
            "Footer", parent=body_style,
            fontSize=8, textColor=LIGHT_TEXT, alignment=TA_CENTER,
        )
        cadence_label = {
            "daily": "Daily Intelligence Brief",
            "weekly": "Weekly Intelligence Brief",
            "monthly": "Monthly Strategic Review",
            "yearly": "Annual Intelligence Review",
        }.get(cadence, "Intelligence Brief")

        elements.append(Paragraph(
            f"{cadence_label} &mdash; Generated {today_display} &mdash; Multi-Agent Intelligence System v2.0",
            footer_style,
        ))

        doc.build(elements)
        logger.info(f"PDF generated: {pdf_path}")
        return pdf_path
    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return None


def _send_email(pdf_path, markdown_text, cadence: str = "daily"):
    """Send newsletter via email.

    Args:
        pdf_path: Path to the PDF file
        markdown_text: The newsletter markdown content
        cadence: Newsletter cadence (daily, weekly, monthly, yearly)
    """
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

        # Build subject line based on cadence
        subject_label = {
            "daily": "Daily Intelligence Brief",
            "weekly": "Weekly Intelligence Brief",
            "monthly": "Monthly Strategic Review",
            "yearly": "Annual Intelligence Review",
        }.get(cadence, "Intelligence Brief")

        msg = MIMEMultipart()
        msg["From"] = email_from
        msg["To"] = email_to
        msg["Subject"] = f"{subject_label} - {today_str}"

        summary = markdown_text[:500].replace("#", "").replace("*", "")
        msg.attach(MIMEText(f"{subject_label} - {today_str}\n\n{summary}\n\n[Full newsletter attached as PDF]", "plain"))

        with open(pdf_path, "rb") as f:
            part = MIMEBase("application", "pdf")
            part.set_payload(f.read())
            encoders.encode_base64(part)
            cadence_filename = f"{cadence}-intelligence-brief-{datetime.utcnow().strftime('%Y-%m-%d')}.pdf"
            part.add_header("Content-Disposition", f'attachment; filename="{cadence_filename}"')
            msg.attach(part)

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)

        logger.info(f"{cadence.upper()} newsletter emailed to {email_to}")
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
