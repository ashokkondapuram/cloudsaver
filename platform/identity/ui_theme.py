"""Platform workspace UI theme presets (mirrors app/ui_theme.py for the identity service)."""
from uuid import UUID

from identity.domain import IdentityError

UI_THEME_PRESETS = ('console', 'midnight-neu', 'aurora-glass')
DEFAULT_UI_THEME_PRESET = 'console'


def normalize_ui_theme_preset(value):
    if value is None or value == '':
        return None
    if not isinstance(value, str) or value not in UI_THEME_PRESETS:
        raise IdentityError('Choose a supported dashboard theme preset.')
    return value


def normalize_workspace_ui_themes(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise IdentityError('Workspace theme assignments must be an object.')
    result = {}
    for tenant_id, preset in value.items():
        try:
            tid = str(UUID(str(tenant_id)))
        except (ValueError, TypeError):
            raise IdentityError('Workspace theme assignments require valid workspace IDs.') from None
        if preset is None:
            continue
        normalized = normalize_ui_theme_preset(preset)
        if normalized == DEFAULT_UI_THEME_PRESET:
            continue
        result[tid] = normalized
    return result


def merge_workspace_ui_themes(current, patch):
    merged = dict(current or {})
    for tenant_id, preset in patch.items():
        if preset is None or preset == DEFAULT_UI_THEME_PRESET:
            merged.pop(tenant_id, None)
        else:
            merged[tenant_id] = preset
    return merged


def effective_ui_theme_preset(platform_themes, tenant_id):
    themes = platform_themes or {}
    preset = themes.get(str(tenant_id), DEFAULT_UI_THEME_PRESET)
    return preset if preset in UI_THEME_PRESETS else DEFAULT_UI_THEME_PRESET
