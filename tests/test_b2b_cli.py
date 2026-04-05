"""Tests for B2B partner CLI commands."""
import pytest
from app import app


@pytest.fixture
def runner():
    return app.test_cli_runner()


class TestPartnerCreate:
    def test_creates_partner_and_keys(self, runner):
        result = runner.invoke(args=[
            "partner", "create",
            "--name", "Test Corp",
            "--email", "dev@testcorp.com",
        ])
        assert result.exit_code == 0
        assert "Test Corp" in result.output
        assert "nc_test_" in result.output
        assert "nc_live_" in result.output

    def test_custom_quota(self, runner):
        result = runner.invoke(args=[
            "partner", "create",
            "--name", "Big Corp",
            "--email", "dev@bigcorp.com",
            "--quota", "1000",
        ])
        assert result.exit_code == 0
        assert "1000" in result.output


class TestPartnerList:
    def test_empty_list(self, runner):
        result = runner.invoke(args=["partner", "list"])
        assert result.exit_code == 0

    def test_shows_created_partner(self, runner):
        runner.invoke(args=[
            "partner", "create",
            "--name", "Listed Corp",
            "--email", "dev@listed.com",
        ])
        result = runner.invoke(args=["partner", "list"])
        assert result.exit_code == 0
        assert "Listed Corp" in result.output


class TestPartnerSuspend:
    def test_suspend_and_reactivate(self, runner):
        runner.invoke(args=[
            "partner", "create",
            "--name", "Suspend Corp",
            "--email", "dev@suspend.com",
        ])
        result = runner.invoke(args=["partner", "suspend", "--name", "Suspend Corp"])
        assert result.exit_code == 0
        assert "suspended" in result.output.lower()

        result = runner.invoke(args=["partner", "reactivate", "--name", "Suspend Corp"])
        assert result.exit_code == 0
        assert "active" in result.output.lower() or "reactivated" in result.output.lower()


class TestPartnerShow:
    def test_shows_partner_details(self, runner):
        runner.invoke(args=[
            "partner", "create",
            "--name", "Show Corp",
            "--email", "dev@show.com",
        ])
        result = runner.invoke(args=["partner", "show", "--name", "Show Corp"])
        assert result.exit_code == 0
        assert "Show Corp" in result.output
        assert "dev@show.com" in result.output

    def test_not_found(self, runner):
        result = runner.invoke(args=["partner", "show", "--name", "Nonexistent"])
        assert result.exit_code != 0


class TestPartnerSetQuota:
    def test_updates_quota(self, runner):
        runner.invoke(args=[
            "partner", "create",
            "--name", "Quota Corp",
            "--email", "dev@quota.com",
        ])
        result = runner.invoke(args=[
            "partner", "set-quota",
            "--name", "Quota Corp",
            "--quota", "2000",
        ])
        assert result.exit_code == 0
        assert "2000" in result.output


class TestPartnerUsage:
    def test_usage_no_month(self, runner):
        runner.invoke(args=[
            "partner", "create",
            "--name", "Usage Corp",
            "--email", "dev@usage.com",
        ])
        result = runner.invoke(args=["partner", "usage", "--name", "Usage Corp"])
        assert result.exit_code == 0

    def test_usage_with_month(self, runner):
        runner.invoke(args=[
            "partner", "create",
            "--name", "Usage Corp2",
            "--email", "dev@usage2.com",
        ])
        result = runner.invoke(args=[
            "partner", "usage",
            "--name", "Usage Corp2",
            "--month", "2026-04",
        ])
        assert result.exit_code == 0


class TestPartnerRevokeRotate:
    def test_revoke_key(self, runner):
        # Create partner and capture key prefix from output
        create_result = runner.invoke(args=[
            "partner", "create",
            "--name", "Revoke Corp",
            "--email", "dev@revoke.com",
        ])
        assert create_result.exit_code == 0
        # Extract a nc_test_ prefix from the output
        for word in create_result.output.split():
            if word.startswith("nc_test_"):
                prefix = word[:16]  # nc_test_ + 8 chars
                break
        else:
            pytest.skip("Could not find nc_test_ key prefix in output")

        result = runner.invoke(args=["partner", "revoke-key", "--prefix", prefix])
        assert result.exit_code == 0
        assert "revoked" in result.output.lower()

    def test_rotate_key(self, runner):
        create_result = runner.invoke(args=[
            "partner", "create",
            "--name", "Rotate Corp",
            "--email", "dev@rotate.com",
        ])
        assert create_result.exit_code == 0
        for word in create_result.output.split():
            if word.startswith("nc_live_"):
                prefix = word[:16]  # nc_live_ + 8 chars
                break
        else:
            pytest.skip("Could not find nc_live_ key prefix in output")

        result = runner.invoke(args=["partner", "rotate-key", "--prefix", prefix])
        assert result.exit_code == 0
        assert "nc_live_" in result.output
