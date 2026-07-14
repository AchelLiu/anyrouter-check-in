from pathlib import Path


def test_checkin_workflow_does_not_cache_browser_profiles():
	workflow = Path('.github/workflows/checkin.yml').read_text(encoding='utf-8')

	assert 'path: .browser_profiles' not in workflow
