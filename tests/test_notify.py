from unittest.mock import MagicMock, patch

import pytest

from utils.notify import NotificationKit


@pytest.fixture(autouse=True)
def _notify_env(monkeypatch):
	monkeypatch.setenv('EMAIL_USER', 'test@example.com')
	monkeypatch.setenv('EMAIL_PASS', 'test_pass')
	monkeypatch.setenv('EMAIL_TO', 'to@example.com')
	monkeypatch.setenv('EMAIL_SENDER', 'sender@example.com')
	monkeypatch.setenv('PUSHPLUS_TOKEN', 'test_token')
	monkeypatch.setenv('SERVERPUSHKEY', 'test_server_key')
	monkeypatch.setenv('DINGDING_WEBHOOK', 'https://oapi.dingtalk.com/robot/send?access_token=test_token')
	monkeypatch.setenv('FEISHU_WEBHOOK', 'https://open.feishu.cn/open-apis/bot/v2/hook/test')
	monkeypatch.setenv('WEIXIN_WEBHOOK', 'http://weixin.example.com')
	monkeypatch.setenv('GOTIFY_URL', 'https://gotify.example.com/message')
	monkeypatch.setenv('GOTIFY_TOKEN', 'test_token')
	monkeypatch.setenv('GOTIFY_PRIORITY', '9')
	monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'test_bot_token')
	monkeypatch.setenv('TELEGRAM_CHAT_ID', '12345')
	monkeypatch.setenv('BARK_KEY', 'test_bark_key')
	monkeypatch.setenv('BARK_SERVER', 'https://api.day.app')


@pytest.fixture
def kit():
	return NotificationKit()


@patch('smtplib.SMTP_SSL')
def test_send_email(mock_smtp, kit):
	mock_server = MagicMock()
	mock_smtp.return_value.__enter__.return_value = mock_server

	kit.send_email('测试标题', '测试内容')

	mock_server.login.assert_called_once_with('test@example.com', 'test_pass')
	mock_server.send_message.assert_called_once()


@patch('httpx.Client')
def test_send_pushplus(mock_client_class, kit):
	mock_client = MagicMock()
	mock_client_class.return_value.__enter__.return_value = mock_client

	kit.send_pushplus('测试标题', '测试内容')

	mock_client.post.assert_called_once_with(
		'http://www.pushplus.plus/send',
		json={'token': 'test_token', 'title': '测试标题', 'content': '测试内容', 'template': 'html'},
	)


@patch('httpx.Client')
def test_send_serverPush(mock_client_class, kit):
	mock_client = MagicMock()
	mock_client_class.return_value.__enter__.return_value = mock_client

	kit.send_serverPush('测试标题', '测试内容')

	mock_client.post.assert_called_once_with(
		'https://sctapi.ftqq.com/test_server_key.send',
		json={'title': '测试标题', 'desp': '测试内容'},
	)


@patch('httpx.Client')
def test_send_dingtalk(mock_client_class, kit):
	mock_client = MagicMock()
	mock_client_class.return_value.__enter__.return_value = mock_client

	kit.send_dingtalk('测试标题', '测试内容')

	mock_client.post.assert_called_once_with(
		'https://oapi.dingtalk.com/robot/send?access_token=test_token',
		json={'msgtype': 'text', 'text': {'content': '测试标题\n测试内容'}},
	)


@patch('httpx.Client')
def test_send_feishu(mock_client_class, kit):
	mock_client = MagicMock()
	mock_client_class.return_value.__enter__.return_value = mock_client

	kit.send_feishu('测试标题', '测试内容')

	mock_client.post.assert_called_once()
	call_args = mock_client.post.call_args
	assert call_args[0][0] == 'https://open.feishu.cn/open-apis/bot/v2/hook/test'
	assert 'card' in call_args[1]['json']


@patch('httpx.Client')
def test_send_wecom(mock_client_class, kit):
	mock_client = MagicMock()
	mock_client_class.return_value.__enter__.return_value = mock_client

	kit.send_wecom('测试标题', '测试内容')

	mock_client.post.assert_called_once_with(
		'http://weixin.example.com',
		json={'msgtype': 'text', 'text': {'content': '测试标题\n测试内容'}},
	)


@patch('httpx.Client')
def test_send_gotify(mock_client_class, kit):
	mock_client = MagicMock()
	mock_client_class.return_value.__enter__.return_value = mock_client

	kit.send_gotify('测试标题', '测试内容')

	mock_client.post.assert_called_once_with(
		'https://gotify.example.com/message?token=test_token',
		json={'title': '测试标题', 'message': '测试内容', 'priority': 9},
	)


@patch('httpx.Client')
def test_send_telegram(mock_client_class, kit):
	mock_client = MagicMock()
	mock_client_class.return_value.__enter__.return_value = mock_client

	kit.send_telegram('测试标题', '测试内容')

	mock_client.post.assert_called_once_with(
		'https://api.telegram.org/bottest_bot_token/sendMessage',
		json={'chat_id': '12345', 'text': '<b>测试标题</b>\n\n测试内容', 'parse_mode': 'HTML'},
	)


@patch('httpx.Client')
def test_send_bark(mock_client_class, kit):
	mock_client = MagicMock()
	mock_client_class.return_value.__enter__.return_value = mock_client

	kit.send_bark('测试标题', '测试内容')

	mock_client.post.assert_called_once_with(
		'https://api.day.app/push',
		json={
			'device_key': 'test_bark_key',
			'title': '测试标题',
			'body': '测试内容',
			'icon': 'https://anyrouter.top/favicon.ico',
			'group': 'AnyRouter',
		},
	)


def test_missing_email_config(monkeypatch):
	monkeypatch.delenv('EMAIL_USER', raising=False)
	monkeypatch.delenv('EMAIL_PASS', raising=False)
	monkeypatch.delenv('EMAIL_TO', raising=False)
	kit = NotificationKit()

	with pytest.raises(ValueError, match='Email configuration not set'):
		kit.send_email('测试', '测试')


def test_missing_pushplus_config(monkeypatch):
	monkeypatch.delenv('PUSHPLUS_TOKEN', raising=False)
	kit = NotificationKit()

	with pytest.raises(ValueError, match='PushPlus Token not configured'):
		kit.send_pushplus('测试', '测试')


def test_missing_gotify_config(monkeypatch):
	monkeypatch.delenv('GOTIFY_URL', raising=False)
	monkeypatch.delenv('GOTIFY_TOKEN', raising=False)
	kit = NotificationKit()

	with pytest.raises(ValueError, match='Gotify URL or Token not configured'):
		kit.send_gotify('测试', '测试')


def test_missing_telegram_config(monkeypatch):
	monkeypatch.delenv('TELEGRAM_BOT_TOKEN', raising=False)
	monkeypatch.delenv('TELEGRAM_CHAT_ID', raising=False)
	kit = NotificationKit()

	with pytest.raises(ValueError, match='Telegram Bot Token or Chat ID not configured'):
		kit.send_telegram('测试', '测试')


def test_missing_bark_config(monkeypatch):
	monkeypatch.delenv('BARK_KEY', raising=False)
	kit = NotificationKit()

	with pytest.raises(ValueError, match='Bark Key not configured'):
		kit.send_bark('测试', '测试')


@patch('utils.notify.NotificationKit.send_email')
@patch('utils.notify.NotificationKit.send_pushplus')
@patch('utils.notify.NotificationKit.send_serverPush')
@patch('utils.notify.NotificationKit.send_dingtalk')
@patch('utils.notify.NotificationKit.send_feishu')
@patch('utils.notify.NotificationKit.send_wecom')
@patch('utils.notify.NotificationKit.send_gotify')
@patch('utils.notify.NotificationKit.send_telegram')
@patch('utils.notify.NotificationKit.send_bark')
def test_push_message(
	mock_bark, mock_telegram, mock_gotify, mock_wecom, mock_feishu, mock_dingtalk, mock_server, mock_pushplus, mock_email, kit
):
	kit.push_message('测试标题', '测试内容')

	mock_email.assert_called_once()
	mock_pushplus.assert_called_once()
	mock_server.assert_called_once()
	mock_dingtalk.assert_called_once()
	mock_feishu.assert_called_once()
	mock_wecom.assert_called_once()
	mock_gotify.assert_called_once()
	mock_telegram.assert_called_once()
	mock_bark.assert_called_once()
