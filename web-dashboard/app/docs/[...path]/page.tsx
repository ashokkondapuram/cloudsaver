import Link from 'next/link';
import {notFound} from 'next/navigation';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  allowedDocStaticParams,
  docTitle,
  normalizeDocFilename,
  readRepoDoc,
} from '../../../lib/repo-docs';

type PageProps = {params: Promise<{path: string[]}>};

export function generateStaticParams() {
  return allowedDocStaticParams();
}

export default async function RepoDocPage({params}: PageProps) {
  const {path: segments} = await params;
  const filename = normalizeDocFilename(segments);
  if (!filename) notFound();

  const markdown = readRepoDoc(filename);
  if (!markdown) notFound();

  const title = docTitle(filename);

  return (
    <div className="page-content doc-guide-page">
      <header className="page-heading">
        <div>
          <span className="eyebrow">Setup guide</span>
          <h1>{title}</h1>
          <p>
            Read-only reference for granting CloudSaver access. Return to{' '}
            <Link className="text-link" href="/settings">Settings</Link> when you are done.
          </p>
        </div>
      </header>
      <article className="panel doc-guide-content">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
          table: ({node: _node, ...props}) => <div className="summary-table-scroll" tabIndex={0} aria-label="Documentation reference table"><table {...props}/></div>,
        }}>{markdown}</ReactMarkdown>
      </article>
    </div>
  );
}
