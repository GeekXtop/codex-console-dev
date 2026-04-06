import sys
import types

from src.core.anyauto import sentinel_browser


class FakePage:
    def __init__(self, token_response):
        self.token_response = token_response
        self.goto_calls = []
        self.wait_calls = []
        self.evaluate_calls = []

    def goto(self, url, wait_until=None, timeout=None):
        self.goto_calls.append({"url": url, "wait_until": wait_until, "timeout": timeout})

    def evaluate(self, script, args=None):
        self.evaluate_calls.append({"script": script, "args": args})
        if "typeof window.SentinelSDK" in script:
            return True
        if "tokenTimeoutMs" in script:
            if callable(self.token_response):
                return self.token_response(args or {})
            return self.token_response
        raise AssertionError(f"unexpected script: {script}")

    def wait_for_timeout(self, timeout_ms):
        self.wait_calls.append(timeout_ms)


class FakeContext:
    def __init__(self, page):
        self.page = page
        self.cookies = []
        self.context_args = None

    def add_cookies(self, cookies):
        self.cookies.extend(cookies)

    def new_page(self):
        return self.page


class FakeBrowser:
    def __init__(self, page, launch_calls):
        self.page = page
        self.launch_calls = launch_calls
        self.closed = False
        self.context = None

    def new_context(self, **kwargs):
        self.context = FakeContext(self.page)
        self.context.context_args = kwargs
        return self.context

    def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self, page, launch_calls):
        self.page = page
        self.launch_calls = launch_calls
        self.browser = None

    def launch(self, **kwargs):
        self.launch_calls.append(kwargs)
        self.browser = FakeBrowser(self.page, self.launch_calls)
        return self.browser


class FakePlaywrightManager:
    def __init__(self, page, launch_calls):
        self.chromium = FakeChromium(page, launch_calls)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _install_fake_playwright(monkeypatch, page, launch_calls):
    sync_api_module = types.ModuleType("playwright.sync_api")
    sync_api_module.sync_playwright = lambda: FakePlaywrightManager(page, launch_calls)
    playwright_module = types.ModuleType("playwright")
    playwright_module.sync_api = sync_api_module
    monkeypatch.setitem(sys.modules, "playwright", playwright_module)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api_module)


def test_get_sentinel_token_via_browser_uses_browser_side_timeout(monkeypatch):
    page = FakePage(lambda _args: {"success": True, "token": '{"p":"req","t":"turn","c":"chal"}'})
    launch_calls = []
    logs = []
    _install_fake_playwright(monkeypatch, page, launch_calls)

    token = sentinel_browser.get_sentinel_token_via_browser(
        flow="oauth_create_account",
        timeout_ms=12000,
        log_fn=logs.append,
    )

    assert token == '{"p":"req","t":"turn","c":"chal"}'
    token_call = next(call for call in page.evaluate_calls if "tokenTimeoutMs" in call["script"])
    assert token_call["args"]["tokenTimeoutMs"] == 12000
    assert page.goto_calls[0]["url"] == "https://auth.openai.com/about-you"
    assert page.goto_calls[0]["timeout"] == 12000
    assert any("Sentinel Browser 成功" in message for message in logs)
    assert launch_calls


def test_get_sentinel_token_via_browser_returns_none_when_token_times_out(monkeypatch):
    page = FakePage(lambda args: {"success": False, "error": f"token timeout after {args['tokenTimeoutMs']}ms"})
    launch_calls = []
    logs = []
    _install_fake_playwright(monkeypatch, page, launch_calls)

    token = sentinel_browser.get_sentinel_token_via_browser(
        flow="oauth_create_account",
        timeout_ms=45000,
        log_fn=logs.append,
    )

    assert token is None
    token_call = next(call for call in page.evaluate_calls if "tokenTimeoutMs" in call["script"])
    assert token_call["args"]["tokenTimeoutMs"] == 20000
    assert "Sentinel Browser 获取 token 超时: 20000ms" in logs

