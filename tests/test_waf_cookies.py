from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from checkin import get_waf_cookies_with_browser


@pytest.fixture
def waf_browser(monkeypatch):
	monkeypatch.setenv('CHECKIN_HEADLESS', 'false')
	monkeypatch.setenv('CHECKIN_HUMANIZE', 'true')
	monkeypatch.setenv('CHECKIN_WAIT_TIMEOUT_MS', '120000')
	page = SimpleNamespace(goto=AsyncMock())
	context = SimpleNamespace(
		new_page=AsyncMock(return_value=page),
		cookies=AsyncMock(return_value=[{'name': 'acw_tc', 'value': 'waf'}, {'name': 'session', 'value': 'private'}]),
		close=AsyncMock(),
	)
	launch = AsyncMock(return_value=context)
	ready = AsyncMock()
	sleep = AsyncMock()
	screenshot = AsyncMock()
	monkeypatch.setattr('checkin.launch_login_context', launch)
	monkeypatch.setattr('checkin.prepare_browser_page', AsyncMock())
	monkeypatch.setattr('checkin.wait_for_waf_ready', ready)
	monkeypatch.setattr('checkin.asyncio.sleep', sleep)
	monkeypatch.setattr('checkin.save_login_screenshot', screenshot)
	return SimpleNamespace(page=page, context=context, launch=launch, ready=ready, sleep=sleep, screenshot=screenshot)


async def test_waf_cookies_use_configured_browser_settings(waf_browser):
	result = await get_waf_cookies_with_browser('test', 'https://example.com/login', ['acw_tc'], use_proxy=True)
	assert result == {'acw_tc': 'waf'}
	settings = waf_browser.launch.call_args.args[0]
	assert settings.headless is False
	assert settings.humanize is True
	assert settings.persist_profile is False
	assert waf_browser.launch.call_args.kwargs == {'use_proxy': True}
	waf_browser.page.goto.assert_awaited_once_with(
		'https://example.com/login', wait_until='domcontentloaded', timeout=120000
	)
	waf_browser.ready.assert_awaited_once_with(waf_browser.page, 120000)
	waf_browser.context.close.assert_awaited_once()


async def test_navigation_timeout_can_recover_without_reloading(waf_browser):
	waf_browser.page.goto.side_effect = PlaywrightTimeoutError('navigation timed out')
	result = await get_waf_cookies_with_browser('test', 'https://example.com/login', ['acw_tc'])
	assert result == {'acw_tc': 'waf'}
	waf_browser.page.goto.assert_awaited_once()
	waf_browser.context.close.assert_awaited_once()


async def test_waf_timeout_retries_then_succeeds(waf_browser):
	waf_browser.page.goto.side_effect = [PlaywrightTimeoutError('navigation timed out'), None]
	waf_browser.ready.side_effect = [PlaywrightTimeoutError('WAF not ready'), None]
	result = await get_waf_cookies_with_browser('test', 'https://example.com/login', ['acw_tc'])
	assert result == {'acw_tc': 'waf'}
	assert waf_browser.page.goto.await_count == 2
	waf_browser.sleep.assert_awaited_once()
	waf_browser.context.close.assert_awaited_once()


async def test_waf_timeout_stops_after_three_attempts(waf_browser):
	waf_browser.page.goto.side_effect = PlaywrightTimeoutError('navigation timed out')
	waf_browser.ready.side_effect = PlaywrightTimeoutError('WAF not ready')
	result = await get_waf_cookies_with_browser('test', 'https://example.com/login', ['acw_tc'])
	assert result is None
	assert waf_browser.page.goto.await_count == 3
	assert waf_browser.sleep.await_count == 2
	waf_browser.context.cookies.assert_not_awaited()
	waf_browser.screenshot.assert_awaited_once()
	waf_browser.context.close.assert_awaited_once()


async def test_missing_cookies_are_retried_and_never_reported_as_success(waf_browser):
	waf_browser.context.cookies.return_value = [{'name': 'session', 'value': 'private'}]
	result = await get_waf_cookies_with_browser('test', 'https://example.com/login', ['acw_tc'])
	assert result is None
	assert waf_browser.page.goto.await_count == 3
	waf_browser.context.close.assert_awaited_once()


async def test_browser_launch_failure_returns_failure(waf_browser):
	waf_browser.launch.side_effect = RuntimeError('browser unavailable')
	result = await get_waf_cookies_with_browser('test', 'https://example.com/login', ['acw_tc'])
	assert result is None
	waf_browser.context.close.assert_not_awaited()
