import type {AtlasNotice, NoticeSeverity} from './atlas-contracts';

/** Map Atlas notice severities onto existing dashboard Notice tones. */
export function noticeTone(severity: NoticeSeverity): 'info' | 'success' | 'warning' | 'error' {
  return severity;
}

export function dedupeNotices(items: AtlasNotice[]): AtlasNotice[] {
  const seen = new Set<string>();
  const out: AtlasNotice[] = [];
  for (const item of items) {
    if (seen.has(item.id)) continue;
    seen.add(item.id);
    out.push(item);
  }
  return out;
}

/** Sileo-style surface: map Atlas notices onto AppShell toasts (no third-party Sileo package). */
export type NoticePublisher = (notice: AtlasNotice) => void;

export function atlasNoticeToToast(notice: AtlasNotice): {tone: ReturnType<typeof noticeTone>; text: string} {
  const text = notice.description ? `${notice.title} — ${notice.description}` : notice.title;
  return {tone: noticeTone(notice.severity), text};
}
