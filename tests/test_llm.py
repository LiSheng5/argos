"""LlmClient 单测：响应解析 / HTTP 错误 / 网络失败 / 无 key —— 全部 mock 网络。"""
import json
from unittest import mock

import pytest

from argos.llm import LlmClient, LlmError, load_api_key


def _resp(payload):
    """构造一个像 urlopen 返回值的假响应对象。"""
    m = mock.MagicMock()
    m.__enter__.return_value = m
    m.read.return_value = json.dumps(payload).encode("utf-8")
    return m


def _client(key="k-123"):
    return LlmClient(base_url="http://mock", model="m", api_key=key, timeout=1.0)


def test_chat_parses_content():
    with mock.patch("argos.llm.urllib.request.urlopen",
                    return_value=_resp({"choices": [{"message": {"content": " 汪！ "}}]})):
        assert _client().chat("s", "u") == "汪！"


def test_chat_sends_auth_and_model():
    with mock.patch("argos.llm.urllib.request.urlopen") as opened:
        opened.return_value = _resp({"choices": [{"message": {"content": "ok"}}]})
        _client().chat("s", "u", max_tokens=80)
        req = opened.call_args[0][0]
        assert req.full_url == "http://mock/chat/completions"
        assert req.headers["Authorization"] == "Bearer k-123"
        body = json.loads(req.data)
        assert body["model"] == "m" and body["messages"][0]["content"] == "s"


def test_http_error_raises():
    import urllib.error
    with mock.patch("argos.llm.urllib.request.urlopen",
                    side_effect=urllib.error.HTTPError("u", 401, "no", {}, None)):
        with pytest.raises(LlmError, match="401"):
            _client().chat("s", "u")


def test_network_error_raises():
    with mock.patch("argos.llm.urllib.request.urlopen",
                    side_effect=TimeoutError("slow")):
        with pytest.raises(LlmError, match="network"):
            _client().chat("s", "u")


def test_bad_shape_raises():
    with mock.patch("argos.llm.urllib.request.urlopen",
                    return_value=_resp({"choices": []})):
        with pytest.raises(LlmError, match="shape"):
            _client().chat("s", "u")


def test_no_key_raises_and_disabled():
    c = LlmClient(base_url="http://mock", api_key="")
    assert not c.enabled()
    with pytest.raises(LlmError, match="no api key"):
        c.chat("s", "u")


def test_load_api_key_env_first(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_API_KEY", "env-key")
    assert load_api_key() == "env-key"
    monkeypatch.delenv("ARGOS_API_KEY")
    (tmp_path / "api_key.txt").write_text("file-key\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert load_api_key() == "file-key"
