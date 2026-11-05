export const UI_THEME_PRESETS = ['console', 'atlas', 'midnight-neu', 'aurora-glass'] as const;
export type UiThemePreset = typeof UI_THEME_PRESETS[number];

export const UI_THEME_META: Record<UiThemePreset, {label: string; description: string}> = {
  console: {label: 'CloudSaver console (slate)', description: 'Default operational console with light and dark modes.'},
  atlas: {label: 'CloudSaver Atlas (enterprise)', description: 'Opaque Atlas tokens for finance and operator workflows; light and dark modes.'},
  'midnight-neu': {label: 'Midnight electric (neumorphism)', description: 'Midnight black canvas, electric blue accents, soft raised panels.'},
  'aurora-glass': {label: 'Aurora glass', description: 'Aurora mesh background with frosted glass panels and cyan–violet highlights.'},
};

export const UI_THEME_LABELS: Record<UiThemePreset, string> = Object.fromEntries(
  UI_THEME_PRESETS.map(id => [id, UI_THEME_META[id].label]),
) as Record<UiThemePreset, string>;
