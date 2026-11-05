/** Visual tokens for AnalyticsChart — Atlas uses `--cs-*` only; other presets use semantic chart vars. */
export type ChartVisualTokens = {
  grid: string;
  line: string;
  muted: string;
  surface: string;
  text: string;
  border: string;
};

const ATLAS_TOKENS: ChartVisualTokens = {
  grid: 'var(--cs-border)',
  line: 'var(--cs-primary)',
  muted: 'var(--cs-muted)',
  surface: 'var(--cs-surface)',
  text: 'var(--cs-text)',
  border: 'var(--cs-border)',
};

const DEFAULT_TOKENS: ChartVisualTokens = {
  grid: 'var(--chart-grid)',
  line: 'var(--chart-line)',
  muted: 'var(--chart-muted)',
  surface: 'var(--surface)',
  text: 'var(--text)',
  border: 'var(--border)',
};

export function chartTokensForUiPreset(preset: string | undefined | null): ChartVisualTokens {
  return preset === 'atlas' ? ATLAS_TOKENS : DEFAULT_TOKENS;
}

/** Shared Nivo theme object — only CSS variable references, no hard-coded palette. */
export function nivoChartTheme(tokens: ChartVisualTokens) {
  return {
    axis: {
      ticks: {text: {fill: tokens.muted, fontSize: 11}},
      domain: {line: {stroke: 'transparent'}},
    },
    grid: {line: {stroke: tokens.grid}},
    tooltip: {
      container: {
        background: tokens.surface,
        color: tokens.text,
        fontSize: 12,
        borderRadius: 8,
        border: `1px solid ${tokens.border}`,
        boxShadow: 'none',
      },
    },
  };
}

export type RechartsChartStyle = {
  gridStroke: string;
  tickFill: string;
  lineStroke: string;
  tooltipBackground: string;
  tooltipBorder: string;
};

export function rechartsChartStyle(tokens: ChartVisualTokens): RechartsChartStyle {
  return {
    gridStroke: tokens.grid,
    tickFill: tokens.muted,
    lineStroke: tokens.line,
    tooltipBackground: tokens.surface,
    tooltipBorder: tokens.border,
  };
}
