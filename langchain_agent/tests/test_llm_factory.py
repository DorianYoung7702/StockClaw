"""Tests for the LLM factory module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestLLMFactory:
    """Verify the factory creates correct model types based on provider."""

    @patch("app.llm.factory.get_settings")
    def test_minimax_provider(self, mock_settings):
        import app.llm.factory as factory_mod
        from app.config import LLMProvider
        from app.llm.factory import create_llm

        settings = MagicMock()
        settings.llm_provider = LLMProvider.MINIMAX
        settings.minimax_api_key = "test-minimax"
        settings.tool_calling_model = "MiniMax-M2.7"
        settings.tool_calling_temperature = 0.0
        settings.reasoning_model = "MiniMax-M2.7"
        settings.reasoning_temperature = 0.3
        settings.max_tokens = 4096
        mock_settings.return_value = settings

        mock_build = MagicMock(return_value=MagicMock())
        patched = dict(factory_mod._BUILDERS)
        patched[LLMProvider.MINIMAX] = mock_build
        with patch.object(factory_mod, "_BUILDERS", patched):
            llm = create_llm(role="tool_calling")
            mock_build.assert_called_once()
            assert llm is not None

    @patch("app.llm.factory.get_settings")
    def test_deepseek_provider(self, mock_settings):
        import app.llm.factory as factory_mod
        from app.config import LLMProvider
        from app.llm.factory import create_llm

        settings = MagicMock()
        settings.llm_provider = LLMProvider.DEEPSEEK
        settings.deepseek_api_key = "sk-test"
        settings.tool_calling_model = "deepseek-chat"
        settings.tool_calling_temperature = 0.0
        settings.reasoning_model = "deepseek-chat"
        settings.reasoning_temperature = 0.3
        settings.max_tokens = 4096
        mock_settings.return_value = settings

        mock_build = MagicMock(return_value=MagicMock())
        patched = dict(factory_mod._BUILDERS)
        patched[LLMProvider.DEEPSEEK] = mock_build
        with patch.object(factory_mod, "_BUILDERS", patched):
            llm = create_llm(role="tool_calling")
            mock_build.assert_called_once()
            assert llm is not None

    @patch("app.llm.factory.get_settings")
    def test_zhipu_provider_import_error(self, mock_settings):
        import app.llm.factory as factory_mod
        from app.config import LLMProvider
        from app.llm.factory import create_llm

        settings = MagicMock()
        settings.llm_provider = LLMProvider.ZHIPU
        settings.zhipu_api_key = "test-key"
        settings.tool_calling_model = "glm-4"
        settings.tool_calling_temperature = 0.0
        settings.max_tokens = 4096
        mock_settings.return_value = settings

        mock_zhipu = MagicMock(side_effect=ImportError("not installed"))
        patched = dict(factory_mod._BUILDERS)
        patched[LLMProvider.ZHIPU] = mock_zhipu
        with patch.object(factory_mod, "_BUILDERS", patched):
            with pytest.raises(ImportError):
                create_llm(role="tool_calling", provider=LLMProvider.ZHIPU)

    @patch("app.llm.factory.get_settings")
    def test_reasoning_role_uses_higher_temperature(self, mock_settings):
        import app.llm.factory as factory_mod
        from app.config import LLMProvider
        from app.llm.factory import create_llm

        settings = MagicMock()
        settings.llm_provider = LLMProvider.DEEPSEEK
        settings.deepseek_api_key = "sk-test"
        settings.tool_calling_model = "deepseek-chat"
        settings.reasoning_model = "deepseek-chat"
        settings.tool_calling_temperature = 0.0
        settings.reasoning_temperature = 0.3
        settings.max_tokens = 4096
        mock_settings.return_value = settings

        mock_build = MagicMock(return_value=MagicMock())
        patched = dict(factory_mod._BUILDERS)
        patched[LLMProvider.DEEPSEEK] = mock_build
        with patch.object(factory_mod, "_BUILDERS", patched):
            create_llm(role="reasoning")
            call_kwargs = mock_build.call_args
            assert call_kwargs.kwargs["temperature"] == 0.3
