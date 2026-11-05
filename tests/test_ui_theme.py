"""UI theme preset validation and effective resolution."""
import pytest

from app.ui_theme import (
    DEFAULT_UI_THEME_PRESET,
    effective_ui_theme_preset,
    merge_workspace_ui_themes,
    normalize_ui_theme_preset,
    normalize_workspace_ui_themes,
)
from app.tenant_registry import normalize_platform


def test_normalize_ui_theme_preset():
    assert normalize_ui_theme_preset('midnight-neu') == 'midnight-neu'
    assert normalize_ui_theme_preset('aurora-glass') == 'aurora-glass'
    assert normalize_ui_theme_preset('atlas') == 'atlas'
    assert normalize_ui_theme_preset('console') == 'console'
    with pytest.raises(ValueError, match='supported'):
        normalize_ui_theme_preset('neon')


def test_workspace_theme_map_and_merge():
    tid = '00000000-0000-4000-8000-000000000001'
    other = '00000000-0000-4000-8000-000000000002'
    assert normalize_workspace_ui_themes({tid: 'midnight-neu'}) == {tid: 'midnight-neu'}
    assert normalize_workspace_ui_themes({tid: 'console'}) == {}
    merged = merge_workspace_ui_themes({tid: 'midnight-neu'}, {other: 'midnight-neu', tid: None})
    assert merged == {other: 'midnight-neu'}
    assert effective_ui_theme_preset(merged, tid) == DEFAULT_UI_THEME_PRESET
    assert effective_ui_theme_preset(merged, other) == 'midnight-neu'


def test_effective_ui_theme_preset_env_default(monkeypatch):
    tid = '00000000-0000-4000-8000-000000000099'
    monkeypatch.setenv('CLOUDSAVER_DEFAULT_UI_THEME_PRESET', 'atlas')
    assert effective_ui_theme_preset({}, tid) == 'atlas'


def test_platform_settings_accepts_workspace_ui_themes():
    base = normalize_platform({'scheduled_scans_enabled': False, 'automated_alerts_enabled': False})
    tid = '00000000-0000-4000-8000-000000000003'
    updated = normalize_platform(dict(base, workspace_ui_themes={tid: 'midnight-neu'}))
    assert updated['workspace_ui_themes'][tid] == 'midnight-neu'
