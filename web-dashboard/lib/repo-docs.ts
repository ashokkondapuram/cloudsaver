import fs from 'node:fs';
import path from 'node:path';

/** Whitelisted setup docs served from the repo `docs/` folder at build time. */
export const ALLOWED_REPO_DOCS: Record<string, string> = {
  'MANAGED_IDENTITY_ROLES.md': 'Managed identity roles',
  'CLOUD_SOURCES.md': 'Cloud sources',
  'ENVIRONMENT.md': 'Environment',
};

export function normalizeDocFilename(segments: string[]): string | null {
  const joined = segments.join('/').replace(/^docs\//, '');
  if (joined.includes('/') || joined.includes('..')) return null;
  return joined in ALLOWED_REPO_DOCS ? joined : null;
}

export function docTitle(filename: string): string {
  return ALLOWED_REPO_DOCS[filename] ?? 'Documentation';
}

export function readRepoDoc(filename: string): string | null {
  if (!(filename in ALLOWED_REPO_DOCS)) return null;
  const candidates = [
    path.join(process.cwd(), 'docs', filename),
    path.join(process.cwd(), '..', 'docs', filename),
  ];
  for (const filePath of candidates) {
    try {
      if (fs.existsSync(/* turbopackIgnore: true */ filePath)) {
        return fs.readFileSync(/* turbopackIgnore: true */ filePath, 'utf8');
      }
    } catch {
      /* try next candidate */
    }
  }
  return null;
}

export function allowedDocStaticParams(): Array<{path: string[]}> {
  return Object.keys(ALLOWED_REPO_DOCS).map((name) => ({path: [name]}));
}
