export const UI_THEME_PRESETS = ['console', 'midnight-neu'] as const;
export type UiThemePreset = typeof UI_THEME_PRESETS[number];
export const DEFAULT_UI_THEME_PRESET: UiThemePreset = 'console';

export const UI_THEME_LABELS: Record<UiThemePreset, string> = {
  console: 'CloudSaver console (slate)',
  'midnight-neu': 'Midnight electric (neumorphism)',
};

export function normalizeUiThemePreset(value: unknown): UiThemePreset {
  if (value === 'midnight-neu') return 'midnight-neu';
  return 'console';
}

export function applyUiThemePreset(preset: UiThemePreset | null | undefined) {
  if (typeof document === 'undefined') return;
  const resolved = normalizeUiThemePreset(preset);
  document.documentElement.dataset.uiPreset = resolved;
  if (resolved === 'midnight-neu') {
    document.documentElement.dataset.theme = 'dark';
  }
}
