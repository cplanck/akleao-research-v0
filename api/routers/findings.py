"""Router for project findings (Key Findings feature)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.database import get_db, Finding, Project, Thread, Message, User
from api.middleware.auth import get_current_user
from api.schemas import FindingCreate, FindingUpdate, FindingResponse

router = APIRouter(prefix="/projects/{project_id}/findings", tags=["findings"])


@router.get("/", response_model=list[FindingResponse])
def list_findings(
    project_id: str,
    thread_id: str | None = Query(None, description="Filter by thread ID"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """List findings for a project, optionally filtered by thread."""
    # Verify project exists and belongs to user
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    query = db.query(Finding).filter(Finding.project_id == project_id)

    if thread_id:
        query = query.filter(Finding.thread_id == thread_id)

    findings = query.order_by(Finding.created_at.desc()).all()
    return findings


@router.get("/{finding_id}", response_model=FindingResponse)
def get_finding(
    project_id: str,
    finding_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Get a specific finding."""
    finding = db.query(Finding).filter(
        Finding.id == finding_id,
        Finding.project_id == project_id
    ).first()

    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    return finding


@router.post("/", response_model=FindingResponse, status_code=201)
def create_finding(
    project_id: str,
    finding: FindingCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Create a new finding."""
    # Verify project exists and belongs to user
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Verify thread exists if provided
    if finding.thread_id:
        thread = db.query(Thread).filter(
            Thread.id == finding.thread_id,
            Thread.project_id == project_id
        ).first()
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")

    # Verify message exists if provided
    if finding.message_id:
        message = db.query(Message).filter(Message.id == finding.message_id).first()
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")

    db_finding = Finding(
        project_id=project_id,
        thread_id=finding.thread_id,
        message_id=finding.message_id,
        content=finding.content,
        note=finding.note
    )

    db.add(db_finding)
    db.commit()
    db.refresh(db_finding)

    return db_finding


@router.patch("/{finding_id}", response_model=FindingResponse)
def update_finding(
    project_id: str,
    finding_id: str,
    updates: FindingUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Update a finding's note."""
    finding = db.query(Finding).filter(
        Finding.id == finding_id,
        Finding.project_id == project_id
    ).first()

    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    if updates.note is not None:
        finding.note = updates.note

    db.commit()
    db.refresh(finding)

    return finding


@router.delete("/{finding_id}", status_code=204)
def delete_finding(
    project_id: str,
    finding_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Delete a finding."""
    finding = db.query(Finding).filter(
        Finding.id == finding_id,
        Finding.project_id == project_id
    ).first()

    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    db.delete(finding)
    db.commit()

    return None


@router.post("/summarize")
def summarize_findings(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Summarize all findings for a project using AI."""
    import os
    from datetime import datetime
    import anthropic

    # Verify project exists and belongs to user
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    findings = db.query(Finding).filter(
        Finding.project_id == project_id
    ).order_by(Finding.created_at.desc()).all()

    if not findings:
        return {"summary": "No findings to summarize."}

    # Get all threads to build hierarchy paths
    thread_ids = [f.thread_id for f in findings if f.thread_id]
    threads_by_id = {}
    if thread_ids:
        # Get all threads for this project to build parent chains
        all_threads = db.query(Thread).filter(
            Thread.project_id == project_id,
            Thread.deleted_at.is_(None)
        ).all()
        threads_by_id = {t.id: t for t in all_threads}

    def get_thread_path(thread_id: str) -> str:
        """Build path like: Thread Title > Subthread Title"""
        if not thread_id or thread_id not in threads_by_id:
            return ""

        path_parts = []
        current = threads_by_id.get(thread_id)
        while current:
            title = current.title or current.context_text or "Untitled"
            if len(title) > 40:
                title = title[:40] + "..."
            path_parts.insert(0, title)
            current = threads_by_id.get(current.parent_thread_id) if current.parent_thread_id else None

        return " > ".join(path_parts) if path_parts else ""

    # Build findings text with context path
    findings_items = []
    for i, f in enumerate(findings):
        thread_path = get_thread_path(f.thread_id)
        context = f" [{thread_path}]" if thread_path else ""
        date = f.created_at.strftime("%b %d")
        note = f" — {f.note}" if f.note else ""

        findings_items.append(f"• \"{f.content}\"{note}{context} ({date})")

    findings_text = "\n".join(findings_items)

    # Calculate date range
    oldest = min(f.created_at for f in findings)
    newest = max(f.created_at for f in findings)
    if oldest.date() == newest.date():
        date_range = oldest.strftime("%B %d, %Y")
    else:
        date_range = f"{oldest.strftime('%b %d')} – {newest.strftime('%b %d, %Y')}"

    # Determine primary thread context for intro
    thread_counts = {}
    for f in findings:
        if f.thread_id and f.thread_id in threads_by_id:
            thread_counts[f.thread_id] = thread_counts.get(f.thread_id, 0) + 1

    intro_context = ""
    if thread_counts:
        # Get the most common thread
        primary_thread_id = max(thread_counts, key=thread_counts.get)
        primary_thread = threads_by_id[primary_thread_id]
        thread_path = get_thread_path(primary_thread_id)
        if len(thread_counts) == 1:
            intro_context = f'from the "{project.name}" project, thread "{thread_path}"'
        else:
            intro_context = f'from the "{project.name}" project (primarily from "{thread_path}")'
    else:
        intro_context = f'from the "{project.name}" project'

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": f"""Summarize these {len(findings)} key findings {intro_context} on {date_range}.

Start with a one-sentence intro like: "The following key findings are from the [Project] project, [thread context], on [date]:"

Then provide 3-5 concise bullet points. The [brackets] show the research path (thread > subthread) where each finding came from.

{findings_text}

Keep the total under 150 words."""
        }]
    )

    summary = response.content[0].text

    # Store summary in project
    project.findings_summary = summary
    project.findings_summary_updated_at = datetime.utcnow()
    db.commit()

    return {"summary": summary}


@router.post("/email")
def email_findings(
    project_id: str,
    email: str = Query(..., description="Recipient email address"),
    content: str | None = Query(None, description="Optional custom content (e.g., AI summary) to send instead of raw findings"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Email findings to a specified address using Mailgun."""
    import os
    import requests
    import re
    from datetime import datetime

    # Verify project exists and belongs to user
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    findings = db.query(Finding).filter(
        Finding.project_id == project_id
    ).order_by(Finding.created_at.desc()).all()

    if not findings and not content:
        raise HTTPException(status_code=400, detail="No findings to send")

    # Get today's date for memo header
    today = datetime.now()
    date_str = today.strftime("%B %d, %Y")
    date_short = today.strftime("%m/%d/%Y")

    def markdown_to_html(text: str) -> str:
        """Convert markdown to HTML for email."""
        # Convert **bold** to <strong>
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        # Convert *italic* to <em> (but not if it's part of **)
        text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<em>\1</em>', text)
        # Convert line breaks and paragraphs
        text = text.replace('\n\n', '</p><p style="margin: 0 0 12px 0; color: #1f2937; line-height: 1.6;">')
        text = text.replace('\n', '<br>')
        text = f'<p style="margin: 0 0 12px 0; color: #1f2937; line-height: 1.6;">{text}</p>'
        # Handle bullet points (- or •)
        text = re.sub(r'<br>[\s]*[-•][\s]*', '<br>&nbsp;&nbsp;• ', text)
        # Handle bullet points at start of paragraph
        text = re.sub(r'<p([^>]*)>[\s]*[-•][\s]*', r'<p\1>&nbsp;&nbsp;• ', text)
        return text

    # If custom content provided (like AI summary), use that
    if content:
        content_html = markdown_to_html(content)

        html_body = f"""
    <html>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="margin-bottom: 24px;">
            <h1 style="color: #1f2937; margin: 0 0 8px 0; font-size: 24px;">
                Key Findings: {project.name}
            </h1>
            <p style="color: #6b7280; margin: 0; font-size: 14px;">
                {date_str}
            </p>
        </div>
        <hr style="border: none; border-top: 2px solid #6366f1; margin: 0 0 20px 0;">
        <div style="margin-top: 20px;">
            {content_html}
        </div>
        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0 16px 0;">
        <p style="font-size: 12px; color: #9ca3af; margin: 0;">Sent from Akleao</p>
    </body>
    </html>
    """
    else:
        # Build email content from findings (no yellow boxes)
        findings_html = "".join([
            f"""<div style="margin-bottom: 16px; padding: 12px 0; border-bottom: 1px solid #e5e7eb;">
                <p style="margin: 0; color: #1f2937; line-height: 1.5;">"{f.content}"</p>
                {f'<p style="margin: 8px 0 0 0; font-style: italic; color: #6b7280;">Note: {f.note}</p>' if f.note else ''}
                <p style="margin: 8px 0 0 0; font-size: 12px; color: #9ca3af;">{f.created_at.strftime('%B %d, %Y at %H:%M')}</p>
            </div>"""
            for f in findings
        ])

        html_body = f"""
    <html>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="margin-bottom: 24px;">
            <h1 style="color: #1f2937; margin: 0 0 8px 0; font-size: 24px;">
                Key Findings: {project.name}
            </h1>
            <p style="color: #6b7280; margin: 0; font-size: 14px;">
                {date_str}
            </p>
        </div>
        <hr style="border: none; border-top: 2px solid #6366f1; margin: 0 0 20px 0;">
        <p style="color: #6b7280;">You have {len(findings)} saved finding{"s" if len(findings) != 1 else ""}:</p>
        {findings_html}
        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0 16px 0;">
        <p style="font-size: 12px; color: #9ca3af; margin: 0;">Sent from Akleao</p>
    </body>
    </html>
    """

    # Send via Mailgun
    mailgun_api_key = os.getenv("MAILGUN_API_KEY")
    mailgun_domain = os.getenv("MAILGUN_DOMAIN")
    mailgun_from = os.getenv("MAILGUN_FROM_EMAIL", f"findings@{mailgun_domain}")

    if not mailgun_api_key or not mailgun_domain:
        raise HTTPException(
            status_code=500,
            detail="Mailgun not configured. Set MAILGUN_API_KEY and MAILGUN_DOMAIN environment variables."
        )

    response = requests.post(
        f"https://api.mailgun.net/v3/{mailgun_domain}/messages",
        auth=("api", mailgun_api_key),
        data={
            "from": mailgun_from,
            "to": email,
            "subject": f"Key Findings: {project.name} ({date_short})",
            "html": html_body,
        }
    )

    if response.status_code != 200:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {response.text}")

    return {"status": "sent", "to": email}
