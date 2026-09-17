"""Tests for the MARS LangGraph wrapper helpers."""
import os
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from ghost_writer.graph import (
    PUBLISH_SENTINEL,
    apply_harness_inference_env,
    last_user_text,
    should_publish,
)


class TestShouldPublish:
    def test_sentinel(self):
        assert should_publish(PUBLISH_SENTINEL) is True

    def test_normal_prompt(self):
        assert should_publish("Write about Kubernetes") is False

    def test_env_mode(self, monkeypatch):
        monkeypatch.setenv("GW_RUN_MODE", "publish")
        assert should_publish("anything") is True

    def test_env_mode_is_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("GW_RUN_MODE", "PUBLISH")
        assert should_publish("anything") is True


class TestLastUserText:
    def test_last_human_message(self):
        state = {
            "messages": [
                HumanMessage(content="first"),
                AIMessage(content="reply"),
                HumanMessage(content="  latest  "),
            ]
        }
        assert last_user_text(state) == "latest"

    def test_dict_messages(self):
        state = {"messages": [{"type": "human", "content": "hello"}]}
        assert last_user_text(state) == "hello"

    def test_empty(self):
        assert last_user_text({"messages": []}) == ""
        assert last_user_text({}) == ""


class TestHarnessEnvMapping:
    def test_maps_key_and_model_when_gradient_unset(self, monkeypatch):
        monkeypatch.setenv("HARNESS_INFERENCE_API_KEY", "harness-key")
        monkeypatch.setenv("HARNESS_INFERENCE_MODEL", "deepseek-v4-pro")
        apply_harness_inference_env()
        assert os.environ["GRADIENT_MODEL_ACCESS_KEY"] == "harness-key"
        assert os.environ["GRADIENT_MODEL"] == "deepseek-v4-pro"

    def test_does_not_override_existing_gradient_vars(self, monkeypatch):
        monkeypatch.setenv("GRADIENT_MODEL_ACCESS_KEY", "existing-key")
        monkeypatch.setenv("GRADIENT_MODEL", "existing-model")
        monkeypatch.setenv("HARNESS_INFERENCE_API_KEY", "harness-key")
        monkeypatch.setenv("HARNESS_INFERENCE_MODEL", "harness-model")
        apply_harness_inference_env()
        assert os.environ["GRADIENT_MODEL_ACCESS_KEY"] == "existing-key"
        assert os.environ["GRADIENT_MODEL"] == "existing-model"


class TestRunRouting:
    def test_sentinel_calls_generate_and_publish(self):
        mock_agent = MagicMock()
        mock_agent.generate_and_publish.return_value = "published"
        with patch("ghost_writer.graph._get_agent", return_value=mock_agent):
            from ghost_writer.graph import run

            result = run({"messages": [HumanMessage(content=PUBLISH_SENTINEL)]})

        mock_agent.generate_and_publish.assert_called_once()
        mock_agent.process_message.assert_not_called()
        assert result["messages"][0].content == "published"

    def test_chat_calls_process_message(self):
        mock_agent = MagicMock()
        mock_agent.process_message.return_value = "draft"
        with patch("ghost_writer.graph._get_agent", return_value=mock_agent):
            from ghost_writer.graph import run

            result = run({"messages": [HumanMessage(content="Write about K8s")]})

        mock_agent.process_message.assert_called_once_with("Write about K8s")
        mock_agent.generate_and_publish.assert_not_called()
        assert result["messages"][0].content == "draft"
