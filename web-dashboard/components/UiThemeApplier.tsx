'use client';

import {useLayoutEffect} from 'react';
import {applyUiThemePreset} from '../lib/ui-theme';
import {useWorkspace} from './WorkspaceProvider';

/** Applies the platform-assigned client theme preset from the connected workspace. */
export function UiThemeApplier() {
  const {workspace} = useWorkspace();
  useLayoutEffect(() => {
    applyUiThemePreset(workspace?.ui_theme_preset);
  }, [workspace?.ui_theme_preset, workspace?.tenant_id]);
  return null;
}
