import json
from unittest.mock import MagicMock

from checkin import (
	compute_acw_sc_v2,
	execute_check_in,
	format_check_in_notification,
	generate_balance_hash,
	get_user_info,
	load_balance_hash,
	parse_cookies,
	save_balance_hash,
)
from utils.config import ProviderConfig


class TestComputeAcwScV2:
	def test_deterministic(self):
		arg1 = 'ff926c7f07e45e2e487a29a6197d3460'
		assert compute_acw_sc_v2(arg1) == compute_acw_sc_v2(arg1)

	def test_returns_string(self):
		result = compute_acw_sc_v2('ff926c7f07e45e2e487a29a6197d3460')
		assert isinstance(result, str)
		assert len(result) >= 32

	def test_different_inputs_different_outputs(self):
		r1 = compute_acw_sc_v2('ff926c7f07e45e2e487a29a6197d3460')
		r2 = compute_acw_sc_v2('aa926c7f07e45e2e487a29a6197d3460')
		assert r1 != r2

	def test_preserves_suffix(self):
		arg1 = 'ff926c7f07e45e2e487a29a6197d3460extrasuffix'
		result = compute_acw_sc_v2(arg1)
		assert result.endswith('extrasuffix')


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

	def test_ignores_used_in_hash(self):
		b1 = {'a': {'quota': 10.0, 'used': 1.0}}
		b2 = {'a': {'quota': 10.0, 'used': 99.0}}
		assert generate_balance_hash(b1) == generate_balance_hash(b2)


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
		assert 'invalid token' in result['error']

	def test_invalid_json(self):
		client = self._make_client(200, text='<html>not json</html>')
		result = get_user_info(client, {}, 'http://test/api/user/self')
		assert result['success'] is False
		assert 'Invalid JSON' in result['error']

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
