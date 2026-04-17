"""Tests for the CLI entry point (mock LLM, no real API calls)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCLI:
    @patch("cli.run_analyze")
    def test_analyze_command_dispatches(self, mock_run):
        import sys
        from unittest.mock import patch as ctx_patch

        mock_run.return_value = None

        with ctx_patch.object(sys, "argv", ["cli.py", "analyze", "AAPL"]):
            with ctx_patch("cli._setup"):
                with ctx_patch("cli._setup_logging"):
                    with ctx_patch("asyncio.run") as mock_asyncio:
                        from cli import main
                        main()
                        mock_asyncio.assert_called_once()

    def test_unknown_command_exits(self):
        import sys
        from unittest.mock import patch as ctx_patch

        with ctx_patch.object(sys, "argv", ["cli.py", "unknown", "foo"]):
            with ctx_patch("cli._setup"):
                with ctx_patch("cli._setup_logging"):
                    from cli import main
                    with pytest.raises(SystemExit) as exc_info:
                        main()
                    assert exc_info.value.code == 2
