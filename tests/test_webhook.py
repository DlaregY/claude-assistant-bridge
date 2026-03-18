"""
Claude Assistant Bridge — Webhook Server Tests
Unit tests for message routing, authentication, and response handling.
Run: python -m pytest tests/ -v
"""

import os
import sys
import json
import time
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from fastapi.testclient import TestClient

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set required env vars before importing the app
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token_123")
os.environ.setdefault("TELEGRAM_ALLOWED_USER_ID", "123456789")
os.environ.setdefault("WEBHOOK_PORT", "8080")
os.environ.setdefault("TASKS_FILE", "/tmp/tasks.json")
os.environ.setdefault("RUN_LOG_FILE", "/tmp/run_log.jsonl")
os.environ.setdefault("LOGS_DIR", "/tmp/cab_logs")
os.environ.setdefault("USER_DISPLAY_NAME", "TestUser")
os.environ.setdefault("TIMEZONE", "America/Chicago")
os.environ.setdefault("CLAUDE_EXE", "echo")  # Use echo as a safe no-op
# Force-set (not setdefault) — .env may have set it to empty string
os.environ["CLOUDFLARE_TUNNEL_URL"] = "https://test.trycloudflare.com"

import webhook_server
from webhook_server import app, ALLOWED_USER_ID


# ---------------------------------------------------------------------------
# Test client
# ---------------------------------------------------------------------------

_update_counter = 1000


@pytest.fixture
def client():
    """FastAPI test client with mocked startup networking."""
    # Clear dedup cache between tests so each test starts fresh
    webhook_server._seen_updates.clear()
    with patch("webhook_server.register_webhook"):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


def telegram_message(text: str, user_id: int = ALLOWED_USER_ID,
                     chat_id: int = 12345, update_id: int = None):
    """Build a minimal Telegram webhook payload with a unique update_id."""
    global _update_counter
    if update_id is None:
        _update_counter += 1
        update_id = _update_counter
    return {
        "update_id": update_id,
        "message": {
            "message_id": 1,
            "from": {
                "id": user_id,
                "first_name": "Test",
                "username": "testuser"
            },
            "chat": {
                "id": chat_id,
                "type": "private"
            },
            "text": text,
            "date": 1700000000
        }
    }


# ---------------------------------------------------------------------------
# Authentication tests
# ---------------------------------------------------------------------------

class TestAuthentication:

    def test_authorized_user_gets_response(self, client):
        """Messages from the whitelisted user ID should be processed."""
        with patch("webhook_server.send_telegram") as mock_send, \
             patch("webhook_server.run_claude", return_value=("Hello there!", True, False)), \
             patch("webhook_server._get_session", return_value=("test-session", True)):
            response = client.post("/webhook", json=telegram_message("hi"))
            assert response.status_code == 200
            assert response.json() == {"ok": True}
            # Give background task time to complete
            time.sleep(0.5)
            # Should have sent the working indicator and the response
            assert mock_send.call_count == 2

    def test_unauthorized_user_is_rejected(self, client):
        """Messages from unknown user IDs should be silently ignored."""
        with patch("webhook_server.send_telegram") as mock_send, \
             patch("webhook_server.run_claude") as mock_claude:
            response = client.post(
                "/webhook",
                json=telegram_message("hack the planet", user_id=9999999)
            )
            assert response.status_code == 200
            assert response.json() == {"ok": True}
            # Nothing should have been sent or executed
            mock_send.assert_not_called()
            mock_claude.assert_not_called()

    def test_empty_text_is_ignored(self, client):
        """Messages with no text (e.g. stickers, photos) should be ignored."""
        payload = telegram_message("dummy")
        del payload["message"]["text"]  # Remove text field
        with patch("webhook_server.send_telegram") as mock_send, \
             patch("webhook_server.run_claude") as mock_claude:
            response = client.post("/webhook", json=payload)
            assert response.status_code == 200
            mock_send.assert_not_called()
            mock_claude.assert_not_called()

    def test_correct_user_id_is_checked(self):
        """ALLOWED_USER_ID should match what's in .env."""
        assert ALLOWED_USER_ID == int(os.environ["TELEGRAM_ALLOWED_USER_ID"])


# ---------------------------------------------------------------------------
# Message routing tests
# ---------------------------------------------------------------------------

class TestMessageRouting:

    def test_working_indicator_sent_before_response(self, client):
        """The '⏳ Working on it...' message should be sent before the response."""
        call_order = []

        def mock_send(chat_id, text):
            call_order.append(text)

        with patch("webhook_server.send_telegram", side_effect=mock_send), \
             patch("webhook_server.run_claude", return_value=("Done!", True, False)), \
             patch("webhook_server._get_session", return_value=("test-session", True)):
            client.post("/webhook", json=telegram_message("do something"))
            time.sleep(0.5)

        assert len(call_order) == 2
        assert "⏳" in call_order[0]
        assert call_order[1] == "Done!"

    def test_response_sent_to_correct_chat_id(self, client):
        """Response should go back to the same chat_id that sent the message."""
        sent_to = []

        def mock_send(chat_id, text):
            sent_to.append(chat_id)

        with patch("webhook_server.send_telegram", side_effect=mock_send), \
             patch("webhook_server.run_claude", return_value=("OK", True, False)), \
             patch("webhook_server._get_session", return_value=("test-session", True)):
            client.post("/webhook", json=telegram_message("hello", chat_id=99999))
            time.sleep(0.5)

        assert all(cid == 99999 for cid in sent_to)

    def test_claude_error_sends_error_message(self, client):
        """If Claude Code raises an exception, an error message should be sent."""
        with patch("webhook_server.send_telegram") as mock_send, \
             patch("webhook_server.run_claude", side_effect=Exception("timeout")), \
             patch("webhook_server._get_session", return_value=("test-session", True)):
            client.post("/webhook", json=telegram_message("do something"))
            time.sleep(0.5)

        # Should still send something back (the error message)
        assert mock_send.called
        last_call_text = mock_send.call_args[0][1]
        assert "❌" in last_call_text

    def test_long_response_is_chunked(self, client):
        """Responses over 4000 chars should be split into multiple messages."""
        long_response = "x" * 8500
        sent_chunks = []

        def mock_post(url, json=None, **kwargs):
            if "sendMessage" in url:
                sent_chunks.append(json.get("text", ""))
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            return mock_resp

        with patch("requests.post", side_effect=mock_post):
            webhook_server.send_telegram(12345, long_response)

        assert len(sent_chunks) == 3
        assert all(len(chunk) <= 4000 for chunk in sent_chunks)
        assert "".join(sent_chunks) == long_response


# ---------------------------------------------------------------------------
# Deduplication tests
# ---------------------------------------------------------------------------

class TestDeduplication:

    def test_duplicate_update_id_is_ignored(self, client):
        """Telegram retries with the same update_id should be dropped."""
        with patch("webhook_server.send_telegram") as mock_send, \
             patch("webhook_server.run_claude", return_value=("OK", True, False)), \
             patch("webhook_server._get_session", return_value=("test-session", True)):
            msg = telegram_message("hello", update_id=42)
            client.post("/webhook", json=msg)
            time.sleep(0.3)
            # Same update_id again (Telegram retry)
            client.post("/webhook", json=msg)
            time.sleep(0.3)

        # run_claude called once → working indicator + response = 2 sends
        assert mock_send.call_count == 2

    def test_new_command_resets_session(self, client):
        """/new command should reset the session and respond."""
        with patch("webhook_server.send_telegram") as mock_send, \
             patch("webhook_server._reset_session") as mock_reset:
            client.post("/webhook", json=telegram_message("/new"))

        mock_reset.assert_called_once()
        mock_send.assert_called_once()
        assert "🔄" in mock_send.call_args[0][1]


# ---------------------------------------------------------------------------
# Skill loading tests
# ---------------------------------------------------------------------------

class TestSkillLoading:

    def test_load_skill_existing_file(self, tmp_path):
        """load_skill should return file contents when the file exists."""
        skill_content = "# Test skill\nDo something useful."
        skill_file = tmp_path / "test_skill.md"
        skill_file.write_text(skill_content)

        with patch("webhook_server.__file__", str(tmp_path / "webhook_server.py")):
            result = webhook_server.load_skill("test_skill.md")

        # Can't easily mock __file__, so test directly
        result = webhook_server.load_skill(str(skill_file))
        assert result == skill_content

    def test_load_skill_missing_file(self):
        """load_skill should return empty string for missing files."""
        result = webhook_server.load_skill("/nonexistent/path/skill.md")
        assert result == ""


# ---------------------------------------------------------------------------
# Claude executable tests
# ---------------------------------------------------------------------------

class TestClaudeResolution:

    def test_env_var_wins(self, monkeypatch):
        """CLAUDE_EXE env var should override auto-detection."""
        monkeypatch.setenv("CLAUDE_EXE", "/custom/path/to/claude")
        result = webhook_server._resolve_claude_exe()
        assert result == "/custom/path/to/claude"

    def test_fallback_on_linux(self, monkeypatch):
        """On Linux with no env var, should return 'claude'."""
        monkeypatch.delenv("CLAUDE_EXE", raising=False)
        with patch("webhook_server.IS_WINDOWS", False):
            result = webhook_server._resolve_claude_exe()
            assert result == "claude"


# ---------------------------------------------------------------------------
# Tunnel URL detection tests
# ---------------------------------------------------------------------------

class TestTunnelDetection:

    def test_get_tunnel_url_success(self):
        """Should parse hostname from cloudflared API response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"hostname": "test-tunnel.trycloudflare.com"}

        with patch("requests.get", return_value=mock_response):
            result = webhook_server.get_tunnel_url(retries=1, delay=0)

        assert result == "https://test-tunnel.trycloudflare.com"

    def test_get_tunnel_url_falls_back_to_env(self, monkeypatch):
        """Should fall back to .env value if cloudflared API is unavailable."""
        monkeypatch.setenv("CLOUDFLARE_TUNNEL_URL", "https://fallback.trycloudflare.com")

        with patch("requests.get", side_effect=Exception("connection refused")):
            result = webhook_server.get_tunnel_url(retries=1, delay=0)

        assert result == "https://fallback.trycloudflare.com"
