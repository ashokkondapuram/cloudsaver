export const UI_THEME_PRESETS = ['console', 'midnight-neu'] as const;
export type UiThemePreset = typeof UI_THEME_PRESETS[number];

export const UI_THEME_LABELS: Record<UiThemePreset, string> = {
  console: 'CloudSaver console (slate)',
  'midnight-neu': 'Midnight electric (neumorphism)',
};
