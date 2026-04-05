"""Flask CLI command group for B2B partner management.

Usage:
    flask partner create --name "Acme Corp" --email "dev@acme.com"
    flask partner list
    flask partner show --name "Acme Corp"
    flask partner usage --name "Acme Corp" [--month 2026-04]
    flask partner suspend --name "Acme Corp"
    flask partner reactivate --name "Acme Corp"
    flask partner set-quota --name "Acme Corp" --quota 1000
    flask partner revoke-key --prefix nc_test_abc12345
    flask partner rotate-key --prefix nc_live_abc12345
"""
from __future__ import annotations

import hashlib
import secrets
import sys
from datetime import datetime, timezone

import click
from flask.cli import AppGroup

from models import _get_db

partner_cli = AppGroup("partner", help="Manage B2B partner accounts and API keys.")

# Key format: nc_{environment}_{32 hex chars}
# Prefix stored in DB: first 16 chars (nc_test_ or nc_live_ + 8 chars)
_KEY_PREFIX_LEN = 16


def _generate_key(environment: str) -> tuple[str, str, str]:
    """Generate a new API key for the given environment.

    Returns:
        (plaintext, sha256_hash, prefix) where prefix is the first
        _KEY_PREFIX_LEN characters of the plaintext key.
    """
    token = secrets.token_hex(16)  # 32 hex chars
    plaintext = f"nc_{environment}_{token}"
    key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    prefix = plaintext[:_KEY_PREFIX_LEN]
    return plaintext, key_hash, prefix


def _find_partner(name: str) -> dict:
    """Look up a partner by name. Exits with error if not found.

    Returns:
        A dict with partner row data (id, name, contact_email, status,
        monthly_quota, notes, created_at).
    """
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT * FROM partners WHERE name = ?", (name,)
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        click.echo(f"Error: partner '{name}' not found.", err=True)
        sys.exit(1)

    return dict(row)


@partner_cli.command("create")
@click.option("--name", required=True, help="Partner organization name.")
@click.option("--email", required=True, help="Partner contact email.")
@click.option("--quota", default=500, show_default=True,
              help="Monthly API request quota.")
@click.option("--notes", default=None, help="Optional internal notes.")
def create_partner(name: str, email: str, quota: int, notes: str | None) -> None:
    """Create a new partner account and issue test + live API keys."""
    conn = _get_db()
    try:
        cursor = conn.execute(
            """
            INSERT INTO partners (name, contact_email, status, monthly_quota, notes)
            VALUES (?, ?, 'active', ?, ?)
            """,
            (name, email, quota, notes),
        )
        partner_id = cursor.lastrowid

        test_plain, test_hash, test_prefix = _generate_key("test")
        live_plain, live_hash, live_prefix = _generate_key("live")

        conn.execute(
            """
            INSERT INTO partner_api_keys (partner_id, key_hash, key_prefix, environment)
            VALUES (?, ?, ?, 'test')
            """,
            (partner_id, test_hash, test_prefix),
        )
        conn.execute(
            """
            INSERT INTO partner_api_keys (partner_id, key_hash, key_prefix, environment)
            VALUES (?, ?, ?, 'live')
            """,
            (partner_id, live_hash, live_prefix),
        )
        conn.commit()
    finally:
        conn.close()

    click.echo(f"Partner created: {name}")
    click.echo(f"  ID:     {partner_id}")
    click.echo(f"  Email:  {email}")
    click.echo(f"  Quota:  {quota} requests/month")
    click.echo(f"  Status: active")
    click.echo("")
    click.echo("API keys (shown once — store securely):")
    click.echo(f"  Test: {test_plain}")
    click.echo(f"  Live: {live_plain}")


@partner_cli.command("list")
def list_partners() -> None:
    """Show all partner accounts."""
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT id, name, status, monthly_quota, contact_email FROM partners ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        click.echo("No partners found.")
        return

    click.echo(f"{'ID':<5} {'Name':<30} {'Status':<12} {'Quota':<8} {'Email'}")
    click.echo("-" * 75)
    for row in rows:
        click.echo(
            f"{row['id']:<5} {row['name']:<30} {row['status']:<12} "
            f"{row['monthly_quota']:<8} {row['contact_email']}"
        )


@partner_cli.command("show")
@click.option("--name", required=True, help="Partner name.")
def show_partner(name: str) -> None:
    """Show detailed info for a partner including all API keys."""
    partner = _find_partner(name)

    conn = _get_db()
    try:
        keys = conn.execute(
            """
            SELECT id, key_prefix, environment, revoked_at, created_at
            FROM partner_api_keys
            WHERE partner_id = ?
            ORDER BY created_at
            """,
            (partner["id"],),
        ).fetchall()
    finally:
        conn.close()

    click.echo(f"Partner: {partner['name']}")
    click.echo(f"  ID:         {partner['id']}")
    click.echo(f"  Email:      {partner['contact_email']}")
    click.echo(f"  Status:     {partner['status']}")
    click.echo(f"  Quota:      {partner['monthly_quota']} requests/month")
    click.echo(f"  Notes:      {partner['notes'] or '—'}")
    click.echo(f"  Created:    {partner['created_at']}")
    click.echo("")
    click.echo(f"API Keys ({len(keys)} total):")
    for key in keys:
        status = "revoked" if key["revoked_at"] else "active"
        click.echo(
            f"  [{key['environment']:5}] {key['key_prefix']}...  "
            f"status={status}  created={key['created_at']}"
        )


@partner_cli.command("usage")
@click.option("--name", required=True, help="Partner name.")
@click.option("--month", default=None,
              help="Month in YYYY-MM format. Defaults to current month.")
def partner_usage(name: str, month: str | None) -> None:
    """Show monthly usage for a partner."""
    partner = _find_partner(name)

    if month is None:
        month = datetime.now(timezone.utc).strftime("%Y-%m")

    conn = _get_db()
    try:
        quota_row = conn.execute(
            """
            SELECT request_count FROM partner_quota_usage
            WHERE partner_id = ? AND period = ?
            """,
            (partner["id"], month),
        ).fetchone()

        # Count from usage log for the same period
        log_count = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM partner_usage_log ul
            JOIN partner_api_keys k ON k.id = ul.key_id
            WHERE k.partner_id = ?
              AND strftime('%Y-%m', ul.created_at) = ?
            """,
            (partner["id"], month),
        ).fetchone()["cnt"]
    finally:
        conn.close()

    quota_count = quota_row["request_count"] if quota_row else 0

    click.echo(f"Usage for {partner['name']} — {month}:")
    click.echo(f"  Quota usage (partner_quota_usage): {quota_count}")
    click.echo(f"  Log count   (partner_usage_log):   {log_count}")
    click.echo(f"  Monthly quota:                     {partner['monthly_quota']}")


@partner_cli.command("suspend")
@click.option("--name", required=True, help="Partner name.")
def suspend_partner(name: str) -> None:
    """Suspend a partner account."""
    partner = _find_partner(name)

    conn = _get_db()
    try:
        conn.execute(
            "UPDATE partners SET status = 'suspended' WHERE id = ?",
            (partner["id"],),
        )
        conn.commit()
    finally:
        conn.close()

    click.echo(f"Partner '{name}' has been suspended.")


@partner_cli.command("reactivate")
@click.option("--name", required=True, help="Partner name.")
def reactivate_partner(name: str) -> None:
    """Reactivate a suspended partner account."""
    partner = _find_partner(name)

    conn = _get_db()
    try:
        conn.execute(
            "UPDATE partners SET status = 'active' WHERE id = ?",
            (partner["id"],),
        )
        conn.commit()
    finally:
        conn.close()

    click.echo(f"Partner '{name}' has been reactivated (status: active).")


@partner_cli.command("set-quota")
@click.option("--name", required=True, help="Partner name.")
@click.option("--quota", required=True, type=int, help="New monthly quota.")
def set_quota(name: str, quota: int) -> None:
    """Update a partner's monthly API request quota."""
    partner = _find_partner(name)

    conn = _get_db()
    try:
        conn.execute(
            "UPDATE partners SET monthly_quota = ? WHERE id = ?",
            (quota, partner["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    click.echo(f"Partner '{name}' quota updated to {quota} requests/month.")


@partner_cli.command("revoke-key")
@click.option("--prefix", required=True, help="Key prefix to revoke (e.g. nc_test_abc12345).")
def revoke_key(prefix: str) -> None:
    """Revoke an API key by its prefix."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT id, revoked_at FROM partner_api_keys WHERE key_prefix = ?",
            (prefix,),
        ).fetchone()

        if row is None:
            click.echo(f"Error: no key found with prefix '{prefix}'.", err=True)
            sys.exit(1)

        if row["revoked_at"] is not None:
            click.echo(f"Key '{prefix}' is already revoked (at {row['revoked_at']}).")
            return

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        conn.execute(
            "UPDATE partner_api_keys SET revoked_at = ? WHERE id = ?",
            (now, row["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    click.echo(f"Key '{prefix}' has been revoked.")


@partner_cli.command("rotate-key")
@click.option("--prefix", required=True,
              help="Key prefix to rotate (e.g. nc_live_abc12345).")
def rotate_key(prefix: str) -> None:
    """Revoke an existing key and issue a new one for the same partner/environment."""
    conn = _get_db()
    try:
        row = conn.execute(
            """
            SELECT k.id, k.partner_id, k.environment, k.revoked_at
            FROM partner_api_keys k
            WHERE k.key_prefix = ?
            """,
            (prefix,),
        ).fetchone()

        if row is None:
            click.echo(f"Error: no key found with prefix '{prefix}'.", err=True)
            sys.exit(1)

        # Revoke old key
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        conn.execute(
            "UPDATE partner_api_keys SET revoked_at = ? WHERE id = ?",
            (now, row["id"]),
        )

        # Issue new key
        env = row["environment"]
        new_plain, new_hash, new_prefix = _generate_key(env)
        conn.execute(
            """
            INSERT INTO partner_api_keys (partner_id, key_hash, key_prefix, environment)
            VALUES (?, ?, ?, ?)
            """,
            (row["partner_id"], new_hash, new_prefix, env),
        )
        conn.commit()
    finally:
        conn.close()

    click.echo(f"Key '{prefix}' revoked.")
    click.echo(f"New {env} key (shown once — store securely):")
    click.echo(f"  {new_plain}")
