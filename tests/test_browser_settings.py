import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from utils.browser import (
	launch_login_context,
	load_browser_login_settings,
	solve_waf_slider_if_present,
	wait_for_waf_ready,
)


def test_browser_login_settings_records_profile_persistence(monkeypatch, tmp_path):
	monkeypatch.setenv('CHECKIN_BROWSER_PROFILE_DIR', str(tmp_path))

	settings = load_browser_login_settings('Account 1', 'agentrouter', persist_profile=False)

	assert settings.persist_profile is False
	assert settings.profile_dir == tmp_path / 'agentrouter' / 'Account 1'


@pytest.mark.asyncio
async def test_launch_login_context_uses_persistent_context_when_enabled(monkeypatch, tmp_path):
	calls = {}
	context = SimpleNamespace()

	async def fake_launch_persistent_context_async(profile_dir, **kwargs):
		calls['profile_dir'] = profile_dir
		calls['kwargs'] = kwargs
		return context

	monkeypatch.setitem(
		sys.modules,
		'cloakbrowser',
		SimpleNamespace(launch_persistent_context_async=fake_launch_persistent_context_async),
	)

	settings = load_browser_login_settings('Account 1', 'anyrouter', persist_profile=True)
	settings = settings.__class__(
		headless=settings.headless,
		humanize=False,
		wait_timeout_ms=settings.wait_timeout_ms,
		profile_dir=tmp_path / 'profiles' / 'anyrouter' / 'Account 1',
		cloakbrowser_binary_path=settings.cloakbrowser_binary_path,
		persist_profile=settings.persist_profile,
	)

	result = await launch_login_context(settings)

	assert result is context
	assert calls['profile_dir'] == str(settings.profile_dir)


@pytest.mark.asyncio
async def test_launch_login_context_closes_browser_for_ephemeral_context(monkeypatch, tmp_path):
	class FakeContext:
		def __init__(self):
			self.closed = False

		async def close(self):
			self.closed = True

	class FakeBrowser:
		def __init__(self):
			self.context = FakeContext()
			self.closed = False
			self.context_kwargs = {}
			self.launch_kwargs = {}

		async def new_context(self, **kwargs):
			self.context_kwargs = kwargs
			return self.context

		async def close(self):
			self.closed = True

	browser = FakeBrowser()

	async def fake_launch_async(**kwargs):
		browser.launch_kwargs = kwargs
		return browser

	monkeypatch.setitem(
		sys.modules,
		'cloakbrowser',
		SimpleNamespace(launch_async=fake_launch_async),
	)

	settings = load_browser_login_settings('Account 1', 'agentrouter', persist_profile=False)
	settings = settings.__class__(
		headless=settings.headless,
		humanize=False,
		wait_timeout_ms=settings.wait_timeout_ms,
		profile_dir=tmp_path / 'profiles' / 'agentrouter' / 'Account 1',
		cloakbrowser_binary_path=settings.cloakbrowser_binary_path,
		persist_profile=settings.persist_profile,
	)

	context = await launch_login_context(settings)
	await context.close()

	assert context.closed is True
	assert browser.closed is True
	assert not settings.profile_dir.exists()


@pytest.mark.asyncio
async def test_waf_slider_solver_skips_normal_page(monkeypatch):
	page = SimpleNamespace()
	detect = AsyncMock(return_value=False)
	find_slider = AsyncMock()
	monkeypatch.setattr('utils.browser._has_waf_slider_challenge', detect)
	monkeypatch.setattr('utils.browser._wait_for_waf_slider', find_slider)

	assert await solve_waf_slider_if_present(page) is True
	find_slider.assert_not_awaited()


@pytest.mark.asyncio
async def test_waf_slider_solver_drags_detected_challenge(monkeypatch):
	page = SimpleNamespace()
	knob = SimpleNamespace()
	track = SimpleNamespace()
	monkeypatch.setattr('utils.browser._has_waf_slider_challenge', AsyncMock(return_value=True))
	find_slider = AsyncMock(return_value=(knob, track))
	drag_slider = AsyncMock()
	wait_for_clear = AsyncMock(return_value=True)
	monkeypatch.setattr('utils.browser._wait_for_waf_slider', find_slider)
	monkeypatch.setattr('utils.browser._drag_waf_slider', drag_slider)
	monkeypatch.setattr('utils.browser._wait_for_waf_slider_clear', wait_for_clear)

	assert await solve_waf_slider_if_present(page) is True
	find_slider.assert_awaited_once()
	drag_slider.assert_awaited_once_with(page, knob, track)
	wait_for_clear.assert_awaited_once()


@pytest.mark.asyncio
async def test_wait_for_waf_ready_rejects_unsolved_slider(monkeypatch):
	page = SimpleNamespace()
	monkeypatch.setattr('utils.browser.solve_waf_slider_if_present', AsyncMock(return_value=False))
	wait_for_site = AsyncMock()
	monkeypatch.setattr('utils.browser.wait_for_site_ready', wait_for_site)

	with pytest.raises(TimeoutError, match='WAF slider verification did not complete'):
		await wait_for_waf_ready(page)

	wait_for_site.assert_awaited_once_with(page, 30_000)


@pytest.mark.asyncio
async def test_wait_for_waf_ready_rechecks_site_after_delayed_slider(monkeypatch):
	page = SimpleNamespace()
	solve_slider = AsyncMock(return_value=True)
	wait_for_site = AsyncMock()
	monkeypatch.setattr('utils.browser.solve_waf_slider_if_present', solve_slider)
	monkeypatch.setattr('utils.browser.wait_for_site_ready', wait_for_site)

	await wait_for_waf_ready(page, 45_000)

	assert wait_for_site.await_count == 2
	wait_for_site.assert_any_await(page, 45_000)
	solve_slider.assert_awaited_once_with(page, 45_000)
