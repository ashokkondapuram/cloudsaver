#!/usr/bin/env node
/**
 * Static contrast audit for Atlas token pairs (light + dark semantic mappings).
 * Run: node scripts/atlas-contrast-audit.mjs
 */
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname, join} from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const css = readFileSync(join(root, 'app/theme-atlas.css'), 'utf8');

function luminance(hex) {
  const raw = hex.replace('#', '');
  const full =
    raw.length === 3
      ? raw
          .split('')
          .map(c => c + c)
          .join('')
      : raw.slice(0, 6);
  const rgb = [0, 2, 4].map(i => parseInt(full.slice(i, i + 2), 16) / 255);
  const linear = rgb.map(c => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function contrast(a, b) {
  const l1 = luminance(a);
  const l2 = luminance(b);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

const pairs = [
  ['light text on surface', '--cs-text', '--cs-surface'],
  ['light muted on surface', '--cs-muted', '--cs-surface'],
  ['dark text on surface', '--cs-text', '--cs-surface'],
];

function readThemeBlock(theme) {
  const block = css.match(new RegExp(`html\\[data-ui-preset=atlas\\]\\[data-theme=${theme}\\][\\s\\S]*?(?=html\\[|$)`));
  return block?.[0] ?? '';
}

let failed = 0;
for (const theme of ['light', 'dark']) {
  const block = readThemeBlock(theme);
  for (const [label, fg, bg] of pairs) {
    const fgM = block.match(new RegExp(`${fg.replace(/-/g, '\\-')}:\\s*(#[0-9a-fA-F]{3,8})`));
    const bgM = block.match(new RegExp(`${bg.replace(/-/g, '\\-')}:\\s*(#[0-9a-fA-F]{3,8})`));
    if (!fgM || !bgM) {
      console.warn(`skip ${theme} ${label}`);
      continue;
    }
    const ratio = contrast(fgM[1], bgM[1]);
    const ok = label.includes('muted') ? ratio >= 4.5 : ratio >= 4.5;
    console.log(`${ok ? 'PASS' : 'FAIL'} ${theme} ${label}: ${ratio.toFixed(2)}:1`);
    if (!ok) failed++;
  }
}

if (failed) process.exit(1);
console.log('Atlas static token contrast audit complete.');
