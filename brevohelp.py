
import logging
import requests

from django.conf import settings

logger = logging.getLogger(__name__)

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def send_email(
    to_email,
    subject,
    html_content=None,
    text_content=None,
    to_name=None,
):
    """
    Send a transactional email using Brevo API.

    Provide either html_content OR text_content, not both.

    Returns:
        {
            "status_code": int,
            "message": str,
            "data": dict | None
        }
    """

    api_key = settings.BREVO_API_KEY
    sender_email = settings.BREVO_SENDER_EMAIL
    sender_name = settings.BREVO_SENDER_NAME

    if not api_key or not sender_email:
        return {
            "status_code": 500,
            "message": "Brevo API credentials are not configured.",
            "data": None,
        }

    if not to_email or not subject:
        return {
            "status_code": 400,
            "message": "Recipient email and subject are required.",
            "data": None,
        }

    # Exactly one content type must be provided.
    if bool(html_content) == bool(text_content):
        return {
            "status_code": 400,
            "message": "Provide either html_content or text_content, not both.",
            "data": None,
        }

    payload = {
        "sender": {
            "name": sender_name,
            "email": sender_email,
        },
        "to": [
            {
                "email": to_email,
                **({"name": to_name} if to_name else {}),
            }
        ],
        "subject": subject,
    }

    if html_content:
        payload["htmlContent"] = html_content
    else:
        payload["textContent"] = text_content

    headers = {
        "accept": "application/json",
        "api-key": api_key,
        "content-type": "application/json",
    }

    try:
        response = requests.post(
            BREVO_API_URL,
            json=payload,
            headers=headers,
            timeout=20,
        )

        try:
            response_data = response.json()
        except ValueError:
            response_data = {"response": response.text}

        if response.status_code not in (200, 201, 202):
            logger.error(
                "Brevo email failed. Status: %s, Response: %s",
                response.status_code,
                response_data,
            )

            return {
                "status_code": response.status_code,
                "message": "Failed to send email.",
                "data": response_data,
            }

        return {
            "status_code": response.status_code,
            "message": "Email sent successfully.",
            "data": response_data,
        }

    except requests.RequestException:
        logger.exception("Brevo API request failed.")

        return {
            "status_code": 503,
            "message": "Email service is temporarily unavailable.",
            "data": None,
        }
