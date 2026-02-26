"""Tests for email_service.py — direct coverage of email construction and error handling.

Currently only tested indirectly via mocking in test_worker.py.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from email_service import send_report_email, send_magic_link_email


class TestSendReportEmail:
    def test_missing_api_key_returns_false(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RESEND_API_KEY", None)
            result = send_report_email("user@example.com", "snap123", "123 Main St")
        assert result is False

    @patch.dict(os.environ, {"RESEND_API_KEY": "re_test_key"})
    def test_successful_send(self):
        mock_resend = MagicMock()
        with patch.dict("sys.modules", {"resend": mock_resend}):
            mock_resend.Emails.send.return_value = {"id": "msg_123"}
            result = send_report_email("user@example.com", "snap123", "123 Main St")
        assert result is True
        mock_resend.Emails.send.assert_called_once()

    @patch.dict(os.environ, {"RESEND_API_KEY": "re_test_key"})
    def test_api_raises_returns_false(self):
        mock_resend = MagicMock()
        with patch.dict("sys.modules", {"resend": mock_resend}):
            mock_resend.Emails.send.side_effect = RuntimeError("API error")
            result = send_report_email("user@example.com", "snap123", "123 Main St")
        assert result is False

    @patch.dict(os.environ, {"RESEND_API_KEY": "re_test_key"})
    def test_html_escapes_address(self):
        mock_resend = MagicMock()
        with patch.dict("sys.modules", {"resend": mock_resend}):
            send_report_email("user@example.com", "snap123", '<script>alert("xss")</script>')
            call_args = mock_resend.Emails.send.call_args[0][0]
            html_body = call_args["html"]
            assert "<script>" not in html_body
            assert "&lt;script&gt;" in html_body

    @patch.dict(os.environ, {"RESEND_API_KEY": "re_test_key", "NESTCHECK_BASE_URL": "https://test.nestcheck.com"})
    def test_uses_base_url(self):
        mock_resend = MagicMock()
        with patch.dict("sys.modules", {"resend": mock_resend}):
            send_report_email("user@example.com", "snap123", "123 Main St")
            call_args = mock_resend.Emails.send.call_args[0][0]
            html_body = call_args["html"]
            assert "https://test.nestcheck.com/s/snap123" in html_body

    @patch.dict(os.environ, {"RESEND_API_KEY": "re_test_key"})
    def test_email_params_structure(self):
        mock_resend = MagicMock()
        with patch.dict("sys.modules", {"resend": mock_resend}):
            send_report_email("user@example.com", "snap123", "123 Main St")
            call_args = mock_resend.Emails.send.call_args[0][0]
            assert call_args["to"] == ["user@example.com"]
            assert "NestCheck" in call_args["from"]
            assert "Report" in call_args["subject"]


class TestSendMagicLinkEmail:
    def test_returns_false_not_implemented(self):
        assert send_magic_link_email("user@example.com") is False
