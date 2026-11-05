export const UI_THEME_PRESETS = ['console', 'atlas', 'midnight-neu', 'aurora-glass'] as const;
export type UiThemePreset = typeof UI_THEME_PRESETS[number];
export const DEFAULT_UI_THEME_PRESET: UiThemePreset = 'atlas';

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

const PRESET_OVERRIDE_KEY = 'cloudsaver:ui:preset-override';

function isUiThemePreset(value: unknown): value is UiThemePreset {
  return typeof value === 'string' && (UI_THEME_PRESETS as readonly string[]).includes(value);
}

/** Per-browser dashboard skin override (Settings → Display). */
export function readUiThemePresetOverride(): UiThemePreset | null {
  if (typeof window === 'undefined') return null;
  try {
    const saved = localStorage.getItem(PRESET_OVERRIDE_KEY);
    return isUiThemePreset(saved) ? saved : null;
  } catch {
    return null;
  }
}

export function writeUiThemePresetOverride(preset: UiThemePreset | null) {
  if (typeof window === 'undefined') return;
  try {
    if (preset) localStorage.setItem(PRESET_OVERRIDE_KEY, preset);
    else localStorage.removeItem(PRESET_OVERRIDE_KEY);
  } catch {}
}

function presetFromEnv(): UiThemePreset | null {
  const raw = process.env.NEXT_PUBLIC_DEFAULT_UI_THEME_PRESET;
  return isUiThemePreset(raw) ? raw : null;
}

/** Override → non-console workspace assignment → build default → Atlas. */
export function resolveUiThemePreset(workspacePreset: unknown): UiThemePreset {
  const override = readUiThemePresetOverride();
  if (override) return override;
  if (isUiThemePreset(workspacePreset) && workspacePreset !== 'console') return workspacePreset;
  const fromEnv = presetFromEnv();
  if (fromEnv) return fromEnv;
  if (typeof document !== 'undefined' && document.documentElement.dataset.uiPreset) {
    const fromDom = normalizeUiThemePreset(document.documentElement.dataset.uiPreset);
    if (fromDom !== 'console') return fromDom;
  }
  return DEFAULT_UI_THEME_PRESET;
}

/** Workspace profile wins; fall back to the DOM preset set by `UiThemeApplier` (Playwright init scripts). */
export function activeUiThemePreset(workspacePreset: unknown): UiThemePreset {
  return resolveUiThemePreset(workspacePreset);
}

export function getThemeMeta(preset: UiThemePreset): ThemeMeta {
  return UI_THEME_META[preset];
}

export function applyUiThemePreset(preset: UiThemePreset | null | undefined) {
  if (typeof document === 'undefined') return;
  const resolved = preset == null ? 'console' : isUiThemePreset(preset) ? preset : normalizeUiThemePreset(preset);
  const meta = getThemeMeta(resolved);
  const root = document.documentElement;
  root.dataset.uiPreset = resolved;
  root.dataset.uiSurface = meta.surface;
  if (meta.appearanceLock) {
    root.dataset.theme = meta.appearanceLock;
  }
}
