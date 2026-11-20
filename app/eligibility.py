"""Strict eligibility filtering for JobsAuto opportunity records."""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse


def parse_deadline(value):
    if not value:
        return None
    try:
        text = str(value).strip().replace('Z', '+00:00')
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def valid_https(value):
    try:
        parsed = urlparse(value or '')
        return parsed.scheme == 'https' and bool(parsed.netloc)
    except Exception:
        return False


def deadline_more_than_days(value, days=7, now=None):
    deadline = parse_deadline(value)
    now = now or datetime.now(timezone.utc)
    return bool(deadline and deadline > now + timedelta(days=days))


def eligible_record(row, now=None, require_current_phd=False):
    return (
        deadline_more_than_days(row.get('deadline'), 7, now)
        and row.get('foreign_eligibility') == 'yes'
        and row.get('bangladesh_eligibility') == 'yes'
        and (not require_current_phd or row.get('current_phd_eligible') == 'yes')
        and row.get('verification_status') == 'verified'
        and valid_https(row.get('official_url'))
        and valid_https(row.get('description_url'))
        and bool(row.get('eligibility_evidence'))
    )
