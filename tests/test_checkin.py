import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from checkin import (
	check_in_account,
	check_in_exit_code,
	execute_check_in,
	format_check_in_notification,
	generate_balance_hash,
	get_user_info,
	load_balance_hash,
	parse_cookies,
	run_agentrouter_browser_check_in,
	save_balance_hash,
)
from utils.config import AccountConfig, AppConfig, ProviderConfig


class TestParseCookies:
	def test_parse_dict(self):
		assert parse_cookies({'session': 'abc'}) == {'session': 'abc'}

	def test_parse_string(self):
		result = parse_cookies('session=abc; token=xyz')
		assert result == {'session': 'abc', 'token': 'xyz'}

	def test_parse_string_with_spaces(self):
		result = parse_cookies('  key1=val1 ;  key2=val2  ')
		assert result == {'key1': 'val1', 'key2': 'val2'}

	def test_parse_empty_string(self):
		assert parse_cookies('') == {}

	def test_parse_none(self):
		assert parse_cookies(None) == {}

	def test_parse_int(self):
		assert parse_cookies(123) == {}

	def test_value_with_equals(self):
		result = parse_cookies('token=abc=def')
		assert result == {'token': 'abc=def'}


class TestGenerateBalanceHash:
	def test_deterministic(self):
		balances = {'a1': {'quota': 10.0, 'used': 5.0}, 'a2': {'quota': 20.0, 'used': 3.0}}
		h1 = generate_balance_hash(balances)
		h2 = generate_balance_hash(balances)
		assert h1 == h2

	def test_different_order_same_hash(self):
		b1 = {'a': {'quota': 1.0, 'used': 0}, 'b': {'quota': 2.0, 'used': 0}}
		b2 = {'b': {'quota': 2.0, 'used': 0}, 'a': {'quota': 1.0, 'used': 0}}
		assert generate_balance_hash(b1) == generate_balance_hash(b2)

	def test_different_values_different_hash(self):
		b1 = {'a': {'quota': 1.0, 'used': 0}}
		b2 = {'a': {'quota': 2.0, 'used': 0}}
		assert generate_balance_hash(b1) != generate_balance_hash(b2)

	def test_empty(self):
		assert generate_balance_hash({}) is not None

	def test_hash_length(self):
		h = generate_balance_hash({'a': {'quota': 1.0, 'used': 0}})
		assert len(h) == 16

	def test_used_affects_hash(self):
		b1 = {'a': {'quota': 10.0, 'used': 1.0}}
		b2 = {'a': {'quota': 10.0, 'used': 99.0}}
		assert generate_balance_hash(b1) != generate_balance_hash(b2)


class TestBalanceHashIO:
	def test_save_and_load(self, tmp_path, monkeypatch):
		hash_file = tmp_path / 'balance_hash.txt'
		monkeypatch.setattr('checkin.BALANCE_HASH_FILE', str(hash_file))

		save_balance_hash('abc123')
		assert load_balance_hash() == 'abc123'

	def test_load_missing_file(self, tmp_path, monkeypatch):
		monkeypatch.setattr('checkin.BALANCE_HASH_FILE', str(tmp_path / 'nonexistent.txt'))
		assert load_balance_hash() is None


class TestGetUserInfo:
	def _make_client(self, status_code, json_data=None, text=''):
		client = MagicMock()
		response = MagicMock()
		response.status_code = status_code
		response.headers = {'content-type': 'application/json' if json_data is not None else 'text/html'}
		if json_data is not None:
			response.json.return_value = json_data
			response.text = json.dumps(json_data)
		else:
			response.json.side_effect = json.JSONDecodeError('err', '', 0)
			response.text = text
		client.get.return_value = response
		return client

	def test_success(self):
		data = {'success': True, 'data': {'quota': 5000000, 'used_quota': 1000000}}
		client = self._make_client(200, data)
		result = get_user_info(client, {}, 'http://test/api/user/self')
		assert result['success'] is True
		assert result['quota'] == 10.0
		assert result['used_quota'] == 2.0

	def test_api_error(self):
		data = {'success': False, 'message': 'invalid token'}
		client = self._make_client(200, data)
		result = get_user_info(client, {}, 'http://test/api/user/self')
		assert result['success'] is False
		assert result['error'] == 'Failed to get user info: HTTP 200'

	def test_invalid_json(self):
		client = self._make_client(200, text='<html>not json</html>')
		result = get_user_info(client, {}, 'http://test/api/user/self')
		assert result['success'] is False
		assert result['non_json'] is True
		assert 'content-type text/html' in result['error']
		assert 'length 21' in result['error']

	def test_http_error(self):
		client = self._make_client(403)
		result = get_user_info(client, {}, 'http://test/api/user/self')
		assert result['success'] is False
		assert '403' in result['error']

	def test_exception(self):
		client = MagicMock()
		client.get.side_effect = Exception('connection timeout')
		result = get_user_info(client, {}, 'http://test/api/user/self')
		assert result['success'] is False
		assert 'connection timeout' in result['error']


class TestExecuteCheckIn:
	def _make_provider(self):
		return ProviderConfig(name='test', domain='https://example.com', sign_in_path='/api/user/sign_in')

	def _make_client(self, status_code, json_data=None, text=''):
		client = MagicMock()
		response = MagicMock()
		response.status_code = status_code
		if json_data is not None:
			response.json.return_value = json_data
			response.text = json.dumps(json_data)
		else:
			response.json.side_effect = json.JSONDecodeError('err', '', 0)
			response.text = text
		client.post.return_value = response
		return client

	def test_success_ret_1(self):
		client = self._make_client(200, {'ret': 1})
		assert execute_check_in(client, 'test', self._make_provider(), {}) is True

	def test_success_code_0(self):
		client = self._make_client(200, {'code': 0})
		assert execute_check_in(client, 'test', self._make_provider(), {}) is True

	def test_success_field(self):
		client = self._make_client(200, {'success': True})
		assert execute_check_in(client, 'test', self._make_provider(), {}) is True

	def test_already_checked_in(self):
		client = self._make_client(200, {'ret': 0, 'msg': '今日已经签到过了'})
		assert execute_check_in(client, 'test', self._make_provider(), {}) is True

	def test_already_signed_english(self):
		client = self._make_client(200, {'ret': 0, 'msg': 'Already checked in'})
		assert execute_check_in(client, 'test', self._make_provider(), {}) is True

	def test_failure(self):
		client = self._make_client(200, {'ret': 0, 'msg': 'some error'})
		assert execute_check_in(client, 'test', self._make_provider(), {}) is False

	def test_non_json_success(self):
		client = self._make_client(200, text='{"success": true}')
		assert execute_check_in(client, 'test', self._make_provider(), {}) is True

	def test_non_json_failure(self):
		client = self._make_client(200, text='<html>error</html>')
		assert execute_check_in(client, 'test', self._make_provider(), {}) is False

	def test_http_error(self):
		client = self._make_client(500)
		assert execute_check_in(client, 'test', self._make_provider(), {}) is False


class TestFormatCheckInNotification:
	def test_with_reward(self):
		detail = {
			'name': 'Account 1',
			'before_quota': 10.0,
			'before_used': 5.0,
			'after_quota': 15.0,
			'after_used': 5.0,
			'check_in_reward': 5.0,
			'usage_increase': 0,
			'balance_change': 5.0,
			'success': True,
		}
		result = format_check_in_notification(detail)
		assert 'Account 1' in result
		assert '+$5.00' in result
		assert '签到获得' in result

	def test_with_usage(self):
		detail = {
			'name': 'Account 1',
			'before_quota': 15.0,
			'before_used': 5.0,
			'after_quota': 17.0,
			'after_used': 8.0,
			'check_in_reward': 5.0,
			'usage_increase': 3.0,
			'balance_change': 2.0,
			'success': True,
		}
		result = format_check_in_notification(detail)
		assert '签到获得' in result
		assert '期间消耗' in result

	def test_no_change(self):
		detail = {
			'name': 'Account 1',
			'before_quota': 10.0,
			'before_used': 5.0,
			'after_quota': 10.0,
			'after_used': 5.0,
			'check_in_reward': 0,
			'usage_increase': 0,
			'balance_change': 0,
			'success': True,
		}
		result = format_check_in_notification(detail)
		assert '无变化' in result

	def test_already_checked_in_with_usage(self):
		detail = {
			'name': 'Account 1',
			'before_quota': 9.0,
			'before_used': 6.0,
			'after_quota': 8.0,
			'after_used': 7.0,
			'check_in_reward': 0,
			'usage_increase': 1.0,
			'balance_change': -1.0,
			'success': True,
		}
		result = format_check_in_notification(detail)
		assert '今日已签到' in result
		assert '期间有使用' in result


class TestCheckInAccountContract:
	async def test_missing_provider_returns_three_values(self):
		account = AccountConfig(cookies={'session': 'test'}, api_user='1', provider='missing')

		result = await check_in_account(account, 0, AppConfig(providers={}))

		assert result == (False, None, None)


class TestAgentRouterBrowserCheckIn:
	async def test_uses_same_browser_context_for_waf_and_user_info(self, monkeypatch):
		responses = [
			{
				'status': 200,
				'contentType': 'application/json',
				'bodyLength': 80,
				'payload': {'success': True, 'data': {'quota': 5000000, 'used_quota': 1000000}},
				'networkError': '',
			},
			{
				'status': 200,
				'contentType': 'application/json',
				'bodyLength': 80,
				'payload': {'success': True, 'data': {'quota': 5500000, 'used_quota': 1000000}},
				'networkError': '',
			},
		]

		class FakePage:
			def __init__(self):
				self.goto = AsyncMock()
				self.evaluate = AsyncMock(side_effect=responses)

		class FakeContext:
			def __init__(self):
				self.page = FakePage()
				self.add_cookies = AsyncMock()
				self.new_page = AsyncMock(return_value=self.page)
				self.cookies = AsyncMock(return_value=[{'name': 'acw_tc', 'value': 'waf'}])
				self.close = AsyncMock()

		context = FakeContext()
		monkeypatch.setattr('checkin.launch_login_context', AsyncMock(return_value=context))
		monkeypatch.setattr('checkin.prepare_browser_page', AsyncMock())
		monkeypatch.setattr('checkin.wait_for_waf_ready', AsyncMock())

		provider = ProviderConfig(
			name='agentrouter',
			domain='https://agentrouter.org',
			sign_in_path=None,
			bypass_method='waf_cookies',
			waf_cookie_names=['acw_tc'],
		)
		account = AccountConfig(
			cookies={'session': 'secret-session'},
			api_user='12345',
			provider='agentrouter',
		)

		result = await run_agentrouter_browser_check_in(
			{'session': 'secret-session'},
			account,
			'AgentRouter',
			provider,
		)

		assert result[0] is True
		assert result[1] is not None
		assert result[2] is not None
		assert result[1]['quota'] == 10.0
		assert result[2]['quota'] == 11.0
		context.add_cookies.assert_awaited_once_with(
			[{'name': 'session', 'value': 'secret-session', 'url': 'https://agentrouter.org/'}]
		)
		assert context.page.evaluate.await_count == 2
		context.close.assert_awaited_once()

	async def test_reports_non_json_metadata_without_body(self, monkeypatch, capsys):
		class FakePage:
			goto = AsyncMock()
			evaluate = AsyncMock(
				return_value={
					'status': 200,
					'contentType': 'text/html; charset=utf-8',
					'bodyLength': 1522,
					'payload': None,
					'networkError': '',
				}
			)

		context = SimpleNamespace(
			add_cookies=AsyncMock(),
			new_page=AsyncMock(return_value=FakePage()),
			cookies=AsyncMock(return_value=[{'name': 'acw_tc', 'value': 'waf'}]),
			close=AsyncMock(),
		)
		monkeypatch.setattr('checkin.launch_login_context', AsyncMock(return_value=context))
		monkeypatch.setattr('checkin.prepare_browser_page', AsyncMock())
		monkeypatch.setattr('checkin.wait_for_waf_ready', AsyncMock())

		provider = ProviderConfig(
			name='agentrouter',
			domain='https://agentrouter.org',
			sign_in_path=None,
			bypass_method='waf_cookies',
			waf_cookie_names=['acw_tc'],
		)
		account = AccountConfig(cookies={'session': 'secret'}, api_user='12345', provider='agentrouter')

		result = await run_agentrouter_browser_check_in(
			{'session': 'secret'},
			account,
			'AgentRouter',
			provider,
		)

		assert result[0] is False
		assert result[2] is not None
		assert result[2]['non_json'] is True
		output = capsys.readouterr().out
		assert 'content-type=text/html' in output
		assert 'length=1522' in output
		assert '<html' not in output
		context.close.assert_awaited_once()


class TestCheckInExitCode:
	def test_all_accounts_must_succeed(self):
		assert check_in_exit_code(4, 4) == 0
		assert check_in_exit_code(2, 4) == 1
		assert check_in_exit_code(0, 4) == 1
		assert check_in_exit_code(0, 0) == 1
