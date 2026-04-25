#!/usr/bin/env python3
"""
AnyRouter.top 自动签到脚本
"""

import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime

import httpx
from dotenv import load_dotenv
from playwright.async_api import async_playwright

from utils.config import AccountConfig, AppConfig, load_accounts_config
from utils.notify import notify

load_dotenv()

BALANCE_HASH_FILE = 'balance_hash.txt'


def load_balance_hash():
	"""加载余额hash"""
	try:
		if os.path.exists(BALANCE_HASH_FILE):
			with open(BALANCE_HASH_FILE, 'r', encoding='utf-8') as f:
				return f.read().strip()
	except Exception:
		pass
	return None


def save_balance_hash(balance_hash):
	"""保存余额hash"""
	try:
		with open(BALANCE_HASH_FILE, 'w', encoding='utf-8') as f:
			f.write(balance_hash)
	except Exception as e:
		print(f'Warning: Failed to save balance hash: {e}')


def generate_balance_hash(balances):
	"""生成余额数据的hash"""
	# 将包含 quota 和 used 的结构转换为简单的 quota 值用于 hash 计算
	simple_balances = {k: v['quota'] for k, v in balances.items()} if balances else {}
	balance_json = json.dumps(simple_balances, sort_keys=True, separators=(',', ':'))
	return hashlib.sha256(balance_json.encode('utf-8')).hexdigest()[:16]


def parse_cookies(cookies_data):
	"""解析 cookies 数据"""
	if isinstance(cookies_data, dict):
		return cookies_data

	if isinstance(cookies_data, str):
		cookies_dict = {}
		for cookie in cookies_data.split(';'):
			if '=' in cookie:
				key, value = cookie.strip().split('=', 1)
				cookies_dict[key] = value
		return cookies_dict
	return {}


async def get_waf_cookies_with_playwright(account_name: str, login_url: str, required_cookies: list[str]):
	"""使用 Playwright 获取 WAF cookies（隐私模式）"""
	print(f'[PROCESSING] {account_name}: Starting browser to get WAF cookies...')

	async with async_playwright() as p:
		import tempfile

		with tempfile.TemporaryDirectory() as temp_dir:
			context = await p.chromium.launch_persistent_context(
				user_data_dir=temp_dir,
				headless=False,
				user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
				viewport={'width': 1920, 'height': 1080},
				args=[
					'--disable-blink-features=AutomationControlled',
					'--disable-dev-shm-usage',
					'--disable-web-security',
					'--disable-features=VizDisplayCompositor',
					'--no-sandbox',
				],
			)

			page = await context.new_page()

			try:
				print(f'[PROCESSING] {account_name}: Access login page to get initial cookies...')

				await page.goto(login_url, wait_until='domcontentloaded')

				try:
					await page.wait_for_load_state('networkidle', timeout=15000)
				except Exception:
					pass

				js_cookies = [c for c in required_cookies if c not in ('acw_tc', 'cdn_sec_tc')]

				if js_cookies:
					content = await page.content()
					if 'aliyun_waf' in content:
						js_cookie_check = ' && '.join(f"document.cookie.includes('{c}')" for c in js_cookies)
						print(f'[INFO] {account_name}: WAF JS challenge detected, waiting for resolution...')

						for attempt in range(3):
							try:
								await page.wait_for_function(js_cookie_check, timeout=15000)
								print(f'[INFO] {account_name}: WAF JS challenge resolved')
								break
							except Exception:
								if attempt < 2:
									print(
										f'[INFO] {account_name}: JS challenge not resolved, reloading (attempt {attempt + 2}/3)...'
									)
									try:
										await page.reload(wait_until='domcontentloaded', timeout=15000)
										await page.wait_for_load_state('networkidle', timeout=15000)
									except Exception:
										pass
								else:
									print(f'[WARNING] {account_name}: JS challenge did not resolve after retries')

				cookies = await page.context.cookies()
				waf_cookies = {}
				for cookie in cookies:
					cookie_name = cookie.get('name')
					cookie_value = cookie.get('value')
					if cookie_name in required_cookies and cookie_value is not None:
						waf_cookies[cookie_name] = cookie_value

				print(f'[INFO] {account_name}: Got {len(waf_cookies)} WAF cookies')

				missing_cookies = [c for c in required_cookies if c not in waf_cookies]

				if missing_cookies:
					print(f'[FAILED] {account_name}: Missing WAF cookies: {missing_cookies}')
					await context.close()
					return None

				print(f'[SUCCESS] {account_name}: Successfully got all WAF cookies')

				await context.close()

				return waf_cookies

			except Exception as e:
				print(f'[FAILED] {account_name}: Error occurred while getting WAF cookies: {e}')
				await context.close()
				return None


def get_user_info(client, headers, user_info_url: str):
	"""获取用户信息"""
	try:
		response = client.get(user_info_url, headers=headers, timeout=30)

		if response.status_code == 200:
			try:
				data = response.json()
				if data.get('success'):
					user_data = data.get('data', {})
					quota = round(user_data.get('quota', 0) / 500000, 2)
					used_quota = round(user_data.get('used_quota', 0) / 500000, 2)
					return {
						'success': True,
						'quota': quota,
						'used_quota': used_quota,
						'display': f':money: Current balance: ${quota}, Used: ${used_quota}',
					}
				else:
					error_msg = data.get('message', 'Unknown error')
					return {'success': False, 'error': f'API error: {error_msg}'}
			except json.JSONDecodeError:
				response_preview = response.text[:200] if response.text else '(empty)'
				return {'success': False, 'error': f'Invalid JSON response: {response_preview}'}
		return {'success': False, 'error': f'Failed to get user info: HTTP {response.status_code}'}
	except Exception as e:
		return {'success': False, 'error': f'Failed to get user info: {str(e)[:50]}...'}


async def check_in_via_browser(account: AccountConfig, account_name: str, provider_config) -> tuple[bool, dict | None]:
	"""当 WAF cookie 提取失败时，通过浏览器直接发起 API 请求"""
	print(f'[INFO] {account_name}: Falling back to browser-based API requests...')

	async with async_playwright() as p:
		import tempfile

		with tempfile.TemporaryDirectory() as temp_dir:
			context = await p.chromium.launch_persistent_context(
				user_data_dir=temp_dir,
				headless=False,
				user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
				viewport={'width': 1920, 'height': 1080},
				args=[
					'--disable-blink-features=AutomationControlled',
					'--disable-dev-shm-usage',
					'--disable-web-security',
					'--disable-features=VizDisplayCompositor',
					'--no-sandbox',
				],
			)

			page = await context.new_page()

			try:
				login_url = f'{provider_config.domain}{provider_config.login_path}'
				await page.goto(login_url, wait_until='domcontentloaded')

				try:
					await page.wait_for_load_state('networkidle', timeout=15000)
				except Exception:
					pass

				user_cookies = parse_cookies(account.cookies)
				domain = provider_config.domain.replace('https://', '').replace('http://', '')
				cookies_to_add = [
					{'name': name, 'value': str(value), 'domain': domain, 'path': '/'}
					for name, value in user_cookies.items()
				]
				await context.add_cookies(cookies_to_add)

				user_info_url = f'{provider_config.domain}{provider_config.user_info_path}'
				api_headers = {
					'Accept': 'application/json, text/plain, */*',
					provider_config.api_user_key: account.api_user,
				}

				print(f'[NETWORK] {account_name}: Fetching user info via browser...')
				user_info_response = await page.evaluate(
					"""async ([url, headers]) => {
						const resp = await fetch(url, {
							method: 'GET',
							headers: headers,
							credentials: 'include',
						});
						return { status: resp.status, body: await resp.text() };
					}""",
					[user_info_url, api_headers],
				)

				user_info = None
				if user_info_response['status'] == 200:
					try:
						data = json.loads(user_info_response['body'])
						if data.get('success'):
							user_data = data.get('data', {})
							quota = round(user_data.get('quota', 0) / 500000, 2)
							used_quota = round(user_data.get('used_quota', 0) / 500000, 2)
							user_info = {
								'success': True,
								'quota': quota,
								'used_quota': used_quota,
								'display': f':money: Current balance: ${quota}, Used: ${used_quota}',
							}
							print(user_info['display'])
						else:
							error_msg = data.get('message', 'Unknown error')
							user_info = {'success': False, 'error': f'API error: {error_msg}'}
							print(f'[FAILED] {account_name}: {error_msg}')
					except json.JSONDecodeError:
						preview = user_info_response['body'][:200]
						user_info = {'success': False, 'error': f'Invalid JSON: {preview}'}
						print(f'[FAILED] {account_name}: Invalid JSON response via browser')
				else:
					user_info = {'success': False, 'error': f'HTTP {user_info_response["status"]}'}
					print(f'[FAILED] {account_name}: HTTP {user_info_response["status"]} via browser')

				if provider_config.needs_manual_check_in():
					sign_in_url = f'{provider_config.domain}{provider_config.sign_in_path}'
					sign_in_headers = {
						'Content-Type': 'application/json',
						'Accept': 'application/json, text/plain, */*',
						'X-Requested-With': 'XMLHttpRequest',
						provider_config.api_user_key: account.api_user,
					}

					print(f'[NETWORK] {account_name}: Executing check-in via browser...')
					sign_in_response = await page.evaluate(
						"""async ([url, headers]) => {
							const resp = await fetch(url, {
								method: 'POST',
								headers: headers,
								credentials: 'include',
							});
							return { status: resp.status, body: await resp.text() };
						}""",
						[sign_in_url, sign_in_headers],
					)

					success = False
					if sign_in_response['status'] == 200:
						try:
							result = json.loads(sign_in_response['body'])
							if result.get('ret') == 1 or result.get('code') == 0 or result.get('success'):
								print(f'[SUCCESS] {account_name}: Check-in successful! (browser)')
								success = True
							else:
								error_msg = result.get('msg', result.get('message', 'Unknown error'))
								print(f'[FAILED] {account_name}: Check-in failed - {error_msg} (browser)')
						except json.JSONDecodeError:
							if 'success' in sign_in_response['body'].lower():
								print(f'[SUCCESS] {account_name}: Check-in successful! (browser)')
								success = True
							else:
								print(f'[FAILED] {account_name}: Invalid response format (browser)')
					else:
						print(f'[FAILED] {account_name}: Check-in failed - HTTP {sign_in_response["status"]} (browser)')

					return success, user_info
				else:
					success = user_info is not None and user_info.get('success', False)
					if success:
						print(f'[INFO] {account_name}: Check-in completed automatically (browser)')
					return success, user_info

			except Exception as e:
				print(f'[FAILED] {account_name}: Browser-based check-in error: {e}')
				return False, None
			finally:
				await context.close()


async def prepare_cookies(account_name: str, provider_config, user_cookies: dict) -> dict | None:
	"""准备请求所需的 cookies（可能包含 WAF cookies）"""
	waf_cookies = {}

	if provider_config.needs_waf_cookies():
		login_url = f'{provider_config.domain}{provider_config.login_path}'
		waf_cookies = await get_waf_cookies_with_playwright(account_name, login_url, provider_config.waf_cookie_names)
		if not waf_cookies:
			print(f'[FAILED] {account_name}: Unable to get WAF cookies')
			return None
	else:
		print(f'[INFO] {account_name}: Bypass WAF not required, using user cookies directly')

	return {**waf_cookies, **user_cookies}


def execute_check_in(client, account_name: str, provider_config, headers: dict):
	"""执行签到请求"""
	print(f'[NETWORK] {account_name}: Executing check-in')

	checkin_headers = headers.copy()
	checkin_headers.update({'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'})

	sign_in_url = f'{provider_config.domain}{provider_config.sign_in_path}'
	response = client.post(sign_in_url, headers=checkin_headers, timeout=30)

	print(f'[RESPONSE] {account_name}: Response status code {response.status_code}')

	if response.status_code == 200:
		try:
			result = response.json()
			if result.get('ret') == 1 or result.get('code') == 0 or result.get('success'):
				print(f'[SUCCESS] {account_name}: Check-in successful!')
				return True
			else:
				error_msg = result.get('msg', result.get('message', 'Unknown error'))
				print(f'[FAILED] {account_name}: Check-in failed - {error_msg}')
				return False
		except json.JSONDecodeError:
			# 如果不是 JSON 响应，检查是否包含成功标识
			if 'success' in response.text.lower():
				print(f'[SUCCESS] {account_name}: Check-in successful!')
				return True
			else:
				print(f'[FAILED] {account_name}: Check-in failed - Invalid response format')
				return False
	else:
		print(f'[FAILED] {account_name}: Check-in failed - HTTP {response.status_code}')
		return False


async def check_in_account(account: AccountConfig, account_index: int, app_config: AppConfig):
	"""为单个账号执行签到操作"""
	account_name = account.get_display_name(account_index)
	print(f'\n[PROCESSING] Starting to process {account_name}')

	provider_config = app_config.get_provider(account.provider)
	if not provider_config:
		print(f'[FAILED] {account_name}: Provider "{account.provider}" not found in configuration')
		return False, None

	print(f'[INFO] {account_name}: Using provider "{account.provider}" ({provider_config.domain})')

	user_cookies = parse_cookies(account.cookies)
	if not user_cookies:
		print(f'[FAILED] {account_name}: Invalid configuration format')
		return False, None

	all_cookies = await prepare_cookies(account_name, provider_config, user_cookies)
	if not all_cookies:
		return await check_in_via_browser(account, account_name, provider_config)

	client = httpx.Client(http2=True, timeout=30.0)

	try:
		client.cookies.update(all_cookies)

		headers = {
			'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
			'Accept': 'application/json, text/plain, */*',
			'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
			'Accept-Encoding': 'gzip, deflate, br, zstd',
			'Referer': provider_config.domain,
			'Origin': provider_config.domain,
			'Connection': 'keep-alive',
			'Sec-Fetch-Dest': 'empty',
			'Sec-Fetch-Mode': 'cors',
			'Sec-Fetch-Site': 'same-origin',
			provider_config.api_user_key: account.api_user,
		}

		user_info_url = f'{provider_config.domain}{provider_config.user_info_path}'
		user_info = get_user_info(client, headers, user_info_url)
		if user_info and user_info.get('success'):
			print(user_info['display'])
		elif user_info:
			print(f'[FAILED] {account_name}: {user_info.get("error", "Unknown error")}')

		if provider_config.needs_manual_check_in():
			success = execute_check_in(client, account_name, provider_config, headers)
			return success, user_info
		else:
			print(f'[INFO] {account_name}: Check-in completed automatically (triggered by user info request)')
			return True, user_info

	except Exception as e:
		print(f'[FAILED] {account_name}: Error occurred during check-in process - {str(e)[:50]}...')
		return False, None
	finally:
		client.close()


async def main():
	"""主函数"""
	print('[SYSTEM] AnyRouter.top multi-account auto check-in script started (using Playwright)')
	print(f'[TIME] Execution time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')

	app_config = AppConfig.load_from_env()
	print(f'[INFO] Loaded {len(app_config.providers)} provider configuration(s)')

	accounts = load_accounts_config()
	if not accounts:
		print('[FAILED] Unable to load account configuration, program exits')
		sys.exit(1)

	print(f'[INFO] Found {len(accounts)} account configurations')

	last_balance_hash = load_balance_hash()

	success_count = 0
	total_count = len(accounts)
	notification_content = []
	current_balances = {}
	need_notify = False  # 是否需要发送通知
	balance_changed = False  # 余额是否有变化

	for i, account in enumerate(accounts):
		account_key = f'account_{i + 1}'
		try:
			success, user_info = await check_in_account(account, i, app_config)
			if success:
				success_count += 1

			should_notify_this_account = False

			if not success:
				should_notify_this_account = True
				need_notify = True
				account_name = account.get_display_name(i)
				print(f'[NOTIFY] {account_name} failed, will send notification')

			if user_info and user_info.get('success'):
				current_quota = user_info['quota']
				current_used = user_info['used_quota']
				current_balances[account_key] = {'quota': current_quota, 'used': current_used}

			if should_notify_this_account:
				account_name = account.get_display_name(i)
				status = '[SUCCESS]' if success else '[FAIL]'
				account_result = f'{status} {account_name}'
				if user_info and user_info.get('success'):
					account_result += f'\n{user_info["display"]}'
				elif user_info:
					account_result += f'\n{user_info.get("error", "Unknown error")}'
				notification_content.append(account_result)

		except Exception as e:
			account_name = account.get_display_name(i)
			print(f'[FAILED] {account_name} processing exception: {e}')
			need_notify = True  # 异常也需要通知
			notification_content.append(f'[FAIL] {account_name} exception: {str(e)[:50]}...')

	# 检查余额变化
	current_balance_hash = generate_balance_hash(current_balances) if current_balances else None
	if current_balance_hash:
		if last_balance_hash is None:
			# 首次运行
			balance_changed = True
			need_notify = True
			print('[NOTIFY] First run detected, will send notification with current balances')
		elif current_balance_hash != last_balance_hash:
			# 余额有变化
			balance_changed = True
			need_notify = True
			print('[NOTIFY] Balance changes detected, will send notification')
		else:
			print('[INFO] No balance changes detected')

	# 为有余额变化的情况添加所有成功账号到通知内容
	if balance_changed:
		for i, account in enumerate(accounts):
			account_key = f'account_{i + 1}'
			if account_key in current_balances:
				account_name = account.get_display_name(i)
				# 只添加成功获取余额的账号，且避免重复添加
				account_result = f'[BALANCE] {account_name}'
				account_result += f'\n:money: Current balance: ${current_balances[account_key]["quota"]}, Used: ${current_balances[account_key]["used"]}'
				# 检查是否已经在通知内容中（避免重复）
				if not any(account_name in item for item in notification_content):
					notification_content.append(account_result)

	# 保存当前余额hash
	if current_balance_hash:
		save_balance_hash(current_balance_hash)

	if need_notify and notification_content:
		# 构建通知内容
		summary = [
			'[STATS] Check-in result statistics:',
			f'[SUCCESS] Success: {success_count}/{total_count}',
			f'[FAIL] Failed: {total_count - success_count}/{total_count}',
		]

		if success_count == total_count:
			summary.append('[SUCCESS] All accounts check-in successful!')
		elif success_count > 0:
			summary.append('[WARN] Some accounts check-in successful')
		else:
			summary.append('[ERROR] All accounts check-in failed')

		time_info = f'[TIME] Execution time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'

		notify_content = '\n\n'.join([time_info, '\n'.join(notification_content), '\n'.join(summary)])

		print(notify_content)
		notify.push_message('AnyRouter Check-in Alert', notify_content, msg_type='text')
		print('[NOTIFY] Notification sent due to failures or balance changes')
	else:
		print('[INFO] All accounts successful and no balance changes detected, notification skipped')

	# 设置退出码
	sys.exit(0 if success_count > 0 else 1)


def run_main():
	"""运行主函数的包装函数"""
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		print('\n[WARNING] Program interrupted by user')
		sys.exit(1)
	except Exception as e:
		print(f'\n[FAILED] Error occurred during program execution: {e}')
		sys.exit(1)


if __name__ == '__main__':
	run_main()
