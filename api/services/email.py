"""Email service for sending magic links via Mailgun."""

import os
import requests


def send_magic_link_email(
    to_email: str,
    magic_link: str,
    is_new_user: bool = False
) -> bool:
    """Send magic link email via Mailgun.

    Args:
        to_email: Recipient email address
        magic_link: The full magic link URL
        is_new_user: Whether this is a new user signup

    Returns:
        True if email was sent successfully

    Raises:
        ValueError: If Mailgun is not configured
        RuntimeError: If email sending fails
    """
    mailgun_api_key = os.getenv("MAILGUN_API_KEY")
    mailgun_domain = os.getenv("MAILGUN_DOMAIN")
    mailgun_from = os.getenv("MAILGUN_FROM_EMAIL", f"noreply@{mailgun_domain}")
    app_name = os.getenv("APP_NAME", "Simage")

    if not mailgun_api_key or not mailgun_domain:
        raise ValueError("Mailgun not configured. Set MAILGUN_API_KEY and MAILGUN_DOMAIN.")

    subject = f"Welcome to {app_name}" if is_new_user else f"Sign in to {app_name}"
    action_text = "complete your registration" if is_new_user else "sign in"

    html_body = f"""
    <html>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 40px 20px; background-color: #f9fafb;">
        <div style="background: white; border-radius: 8px; padding: 40px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
            <h1 style="color: #1f2937; margin: 0 0 24px 0; font-size: 24px; font-weight: 600;">
                {subject}
            </h1>
            <p style="color: #4b5563; line-height: 1.6; margin: 0 0 24px 0;">
                Click the button below to {action_text}. This link will expire in 15 minutes.
            </p>
            <div style="margin: 32px 0;">
                <a href="{magic_link}"
                   style="background-color: #6366f1; color: white; padding: 14px 28px;
                          text-decoration: none; border-radius: 6px; display: inline-block;
                          font-weight: 500; font-size: 16px;">
                    Sign In
                </a>
            </div>
            <p style="color: #9ca3af; font-size: 14px; margin: 24px 0 0 0;">
                If you didn't request this email, you can safely ignore it.
            </p>
        </div>
        <p style="color: #9ca3af; font-size: 12px; text-align: center; margin: 24px 0 0 0;">
            If the button doesn't work, copy and paste this link:<br>
            <a href="{magic_link}" style="color: #6366f1; word-break: break-all;">{magic_link}</a>
        </p>
    </body>
    </html>
    """

    response = requests.post(
        f"https://api.mailgun.net/v3/{mailgun_domain}/messages",
        auth=("api", mailgun_api_key),
        data={
            "from": mailgun_from,
            "to": to_email,
            "subject": subject,
            "html": html_body,
        }
    )

    if response.status_code != 200:
        raise RuntimeError(f"Failed to send email: {response.text}")

    return True
