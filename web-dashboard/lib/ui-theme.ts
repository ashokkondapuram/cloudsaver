export const UI_THEME_PRESETS = ['console', 'atlas', 'midnight-neu', 'aurora-glass'] as const;
export type UiThemePreset = typeof UI_THEME_PRESETS[number];
export const DEFAULT_UI_THEME_PRESET: UiThemePreset = 'console';

export type UiSurfaceStyle = 'flat' | 'neumorphic' | 'glass';

export type ThemeMeta = {
  label: string;
  description: string;
  surface: UiSurfaceStyle;
  /** When set, the light/dark toggle is hidden and this mode is enforced. */
  appearanceLock?: 'dark';
};

export const UI_THEME_META: Record<UiThemePreset, ThemeMeta> = {
  console: {
    label: 'CloudSaver console (slate)',
    description: 'Default operational console with light and dark modes.',
    surface: 'flat',
  },
  atlas: {
    label: 'CloudSaver Atlas (enterprise)',
    description: 'Opaque Atlas tokens for finance and operator workflows; light and dark modes.',
    surface: 'flat',
  },
  'midnight-neu': {
    label: 'Midnight electric (neumorphism)',
    description: 'Midnight black canvas, electric blue accents, soft raised panels.',
    surface: 'neumorphic',
    appearanceLock: 'dark',
  },
  'aurora-glass': {
    label: 'Aurora glass',
    description: 'Aurora mesh background with frosted glass panels and cyan–violet highlights.',
    surface: 'glass',
    appearanceLock: 'dark',
  },
};

export const UI_THEME_LABELS: Record<UiThemePreset, string> = Object.fromEntries(
  UI_THEME_PRESETS.map(id => [id, UI_THEME_META[id].label]),
) as Record<UiThemePreset, string>;

export function normalizeUiThemePreset(value: unknown): UiThemePreset {
  if (value === 'atlas' || value === 'midnight-neu' || value === 'aurora-glass') return value;
  return 'console';
}

export function getThemeMeta(preset: UiThemePreset): ThemeMeta {
  return UI_THEME_META[preset];
}

export function applyUiThemePreset(preset: UiThemePreset | null | undefined) {
  if (typeof document === 'undefined') return;
  const resolved = normalizeUiThemePreset(preset);
  const meta = getThemeMeta(resolved);
  const root = document.documentElement;
  root.dataset.uiPreset = resolved;
  root.dataset.uiSurface = meta.surface;
  if (meta.appearanceLock) {
    root.dataset.theme = meta.appearanceLock;
  }
}
