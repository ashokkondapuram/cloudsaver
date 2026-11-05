'use client';

import {useLayoutEffect} from 'react';
import {applyUiThemePreset, resolveUiThemePreset} from '../lib/ui-theme';
import {useWorkspace} from './WorkspaceProvider';

/** Applies workspace, operator, env, and local display overrides for the dashboard skin. */
export function UiThemeApplier() {
  const {workspace} = useWorkspace();
  useLayoutEffect(() => {
    applyUiThemePreset(resolveUiThemePreset(workspace?.ui_theme_preset));
  }, [workspace?.ui_theme_preset, workspace?.tenant_id]);
  return null;
}
