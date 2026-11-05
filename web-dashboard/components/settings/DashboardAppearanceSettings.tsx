'use client';

import {useState} from 'react';
import {Check, Palette} from 'lucide-react';
import {
  UI_THEME_META,
  UI_THEME_PRESETS,
  applyUiThemePreset,
  readUiThemePresetOverride,
  resolveUiThemePreset,
  writeUiThemePresetOverride,
  type UiThemePreset,
} from '../../lib/ui-theme';
import {useWorkspace} from '../WorkspaceProvider';
import {Notice, SectionTitle} from '../ui/shared';

const swatches: Record<UiThemePreset, string[]> = {
  console: ['#1e293b', '#4f46e5', '#f8fafc'],
  atlas: ['#0b1220', '#1d4ed8', '#f5f7fa'],
  'midnight-neu': ['#050508', '#38bdf8', '#111827'],
  'aurora-glass': ['#0c0418', '#22d3ee', '#312e81'],
};

export function DashboardAppearanceSettings() {
  const {workspace, notify} = useWorkspace();
  const assigned = resolveUiThemePreset(workspace?.ui_theme_preset);
  const [active, setActive] = useState<UiThemePreset>(() => assigned);

  function choose(preset: UiThemePreset) {
    writeUiThemePresetOverride(preset);
    applyUiThemePreset(preset);
    setActive(preset);
    notify(
      preset === 'atlas'
        ? 'Atlas enterprise appearance applied — charts use Nivo and finance tokens.'
        : `${UI_THEME_META[preset].label} applied in this browser.`,
    );
  }

  return (
    <section className="panel dashboard-appearance-panel">
      <SectionTitle title="Dashboard appearance">
        Choose the CloudSaver visual system for this browser. Atlas enables enterprise finance tokens, Nivo charts, and
        dense operator layouts.
      </SectionTitle>
      {workspace?.ui_theme_preset && workspace.ui_theme_preset !== 'console' && !readUiThemePresetOverride() && (
        <Notice tone="info">
          Your workspace default is <strong>{UI_THEME_META[workspace.ui_theme_preset].label}</strong>. Pick another skin
          below to preview locally.
        </Notice>
      )}
      <div className="appearance-grid" role="list">
        {UI_THEME_PRESETS.map(preset => {
          const meta = UI_THEME_META[preset];
          const selected = active === preset;
          return (
            <button
              key={preset}
              type="button"
              role="listitem"
              className={`appearance-card ${selected ? 'selected' : ''}`}
              aria-pressed={selected}
              onClick={() => choose(preset)}
            >
              <span className="appearance-preview" aria-hidden="true">
                {swatches[preset].map(color => (
                  <i key={color} style={{background: color}}/>
                ))}
              </span>
              <span className="appearance-copy">
                <strong>{meta.label}</strong>
                <span>{meta.description}</span>
              </span>
              {selected ? (
                <span className="appearance-selected">
                  <Check size={16} aria-hidden="true"/>
                  Active
                </span>
              ) : (
                <span className="appearance-cta">
                  <Palette size={15} aria-hidden="true"/>
                  Use this skin
                </span>
              )}
            </button>
          );
        })}
      </div>
    </section>
  );
}
