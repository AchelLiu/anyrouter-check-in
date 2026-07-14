import json

from utils.config import AccountConfig, AppConfig, ProviderConfig, load_accounts_config


class TestProviderConfig:
	def test_from_dict_minimal(self):
		config = ProviderConfig.from_dict('test', {'domain': 'https://example.com'})
		assert config.name == 'test'
		assert config.domain == 'https://example.com'
		assert config.login_path == '/login'
		assert config.sign_in_path == '/api/user/sign_in'
		assert config.api_user_key == 'new-api-user'
		assert config.bypass_method is None

	def test_from_dict_full(self):
		data = {
			'domain': 'https://example.com',
			'login_path': '/auth',
			'sign_in_path': '/api/checkin',
			'user_info_path': '/api/me',
			'api_user_key': 'x-api-user',
			'bypass_method': 'waf_cookies',
			'waf_cookie_names': ['acw_tc', 'cdn_sec_tc'],
		}
		config = ProviderConfig.from_dict('custom', data)
		assert config.login_path == '/auth'
		assert config.sign_in_path == '/api/checkin'
		assert config.api_user_key == 'x-api-user'
		assert config.bypass_method == 'waf_cookies'
		assert set(config.waf_cookie_names) == {'acw_tc', 'cdn_sec_tc'}

	def test_post_init_clears_bypass_when_no_valid_cookies(self):
		config = ProviderConfig(
			name='test',
			domain='https://example.com',
			bypass_method='waf_cookies',
			waf_cookie_names=['', '  ', None],
		)
		assert config.bypass_method is None
		assert config.waf_cookie_names == []

	def test_post_init_strips_cookie_names(self):
		config = ProviderConfig(
			name='test',
			domain='https://example.com',
			bypass_method='waf_cookies',
			waf_cookie_names=[' acw_tc ', 'cdn_sec_tc'],
		)
		assert 'acw_tc' in config.waf_cookie_names
		assert 'cdn_sec_tc' in config.waf_cookie_names

	def test_needs_waf_cookies(self):
		config = ProviderConfig(
			name='test',
			domain='https://example.com',
			bypass_method='waf_cookies',
			waf_cookie_names=['acw_tc'],
		)
		assert config.needs_waf_cookies() is True

	def test_no_waf_cookies_needed(self):
		config = ProviderConfig(name='test', domain='https://example.com')
		assert config.needs_waf_cookies() is False

	def test_needs_manual_check_in(self):
		config = ProviderConfig(name='test', domain='https://example.com', sign_in_path='/api/sign_in')
		assert config.needs_manual_check_in() is True

	def test_no_manual_check_in(self):
		config = ProviderConfig(name='test', domain='https://example.com', sign_in_path=None)
		assert config.needs_manual_check_in() is False


class TestAppConfig:
	def test_load_default_providers(self, monkeypatch):
		monkeypatch.delenv('PROVIDERS', raising=False)
		config = AppConfig.load_from_env()
		assert 'anyrouter' in config.providers
		assert 'agentrouter' in config.providers
		assert config.providers['anyrouter'].domain == 'https://anyrouter.top'
		assert config.providers['agentrouter'].sign_in_path is None

	def test_load_custom_providers(self, monkeypatch):
		custom = {'myrouter': {'domain': 'https://myrouter.com', 'api_user_key': 'x-custom'}}
		monkeypatch.setenv('PROVIDERS', json.dumps(custom))
		config = AppConfig.load_from_env()
		assert 'myrouter' in config.providers
		assert config.providers['myrouter'].api_user_key == 'x-custom'

	def test_custom_provider_overrides_default(self, monkeypatch):
		custom = {'anyrouter': {'domain': 'https://custom-anyrouter.com'}}
		monkeypatch.setenv('PROVIDERS', json.dumps(custom))
		config = AppConfig.load_from_env()
		assert config.providers['anyrouter'].domain == 'https://custom-anyrouter.com'

	def test_invalid_providers_json(self, monkeypatch):
		monkeypatch.setenv('PROVIDERS', 'not-json')
		config = AppConfig.load_from_env()
		assert 'anyrouter' in config.providers

	def test_providers_not_dict(self, monkeypatch):
		monkeypatch.setenv('PROVIDERS', '["not", "a", "dict"]')
		config = AppConfig.load_from_env()
		assert 'anyrouter' in config.providers

	def test_get_provider(self, monkeypatch):
		monkeypatch.delenv('PROVIDERS', raising=False)
		config = AppConfig.load_from_env()
		assert config.get_provider('anyrouter') is not None
		assert config.get_provider('nonexistent') is None


class TestAccountConfig:
	def test_from_dict_minimal(self):
		data = {'cookies': {'session': 'abc'}, 'api_user': 'user123'}
		account = AccountConfig.from_dict(data, 0)
		assert account.cookies == {'session': 'abc'}
		assert account.api_user == 'user123'
		assert account.provider == 'anyrouter'

	def test_from_dict_with_name_and_provider(self):
		data = {'cookies': 'session=abc', 'api_user': 'user123', 'provider': 'agentrouter', 'name': 'My Account'}
		account = AccountConfig.from_dict(data, 0)
		assert account.provider == 'agentrouter'
		assert account.name == 'My Account'

	def test_get_display_name_with_name(self):
		account = AccountConfig(cookies={}, api_user='u', name='Test')
		assert account.get_display_name(0) == 'Test'

	def test_get_display_name_without_name(self):
		account = AccountConfig(cookies={}, api_user='u')
		assert account.get_display_name(2) == 'Account 3'


class TestLoadAccountsConfig:
	def test_missing_env(self, monkeypatch):
		monkeypatch.delenv('ANYROUTER_ACCOUNTS', raising=False)
		assert load_accounts_config() is None

	def test_valid_config(self, monkeypatch):
		accounts = [
			{'cookies': {'s': '1'}, 'api_user': 'u1'},
			{'cookies': 'session=abc', 'api_user': 'u2', 'name': 'Test'},
		]
		monkeypatch.setenv('ANYROUTER_ACCOUNTS', json.dumps(accounts))
		result = load_accounts_config()
		assert result is not None
		assert len(result) == 2
		assert result[1].name == 'Test'

	def test_not_array(self, monkeypatch):
		monkeypatch.setenv('ANYROUTER_ACCOUNTS', '{"not": "array"}')
		assert load_accounts_config() is None

	def test_missing_required_fields(self, monkeypatch):
		monkeypatch.setenv('ANYROUTER_ACCOUNTS', json.dumps([{'cookies': {'s': '1'}}]))
		assert load_accounts_config() is None

	def test_empty_name_rejected(self, monkeypatch):
		monkeypatch.setenv('ANYROUTER_ACCOUNTS', json.dumps([{'cookies': {'s': '1'}, 'api_user': 'u', 'name': ''}]))
		assert load_accounts_config() is None

	def test_invalid_json(self, monkeypatch):
		monkeypatch.setenv('ANYROUTER_ACCOUNTS', 'not-json')
		assert load_accounts_config() is None
