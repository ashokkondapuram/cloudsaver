import type {Metadata} from 'next';
import type {ReactNode} from 'react';
import '@fontsource-variable/inter';
import '@fontsource-variable/jetbrains-mono';
import './globals.css';
import {AppShell} from '../components/AppShell';
import {SessionProvider} from '../components/SessionProvider';
import {ThemeProvider} from '../components/ThemeProvider';

// Rendering per request lets Next.js apply the CSP nonce set in proxy.ts to its scripts.
export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: 'CloudSaver | Platform portal',
  description: 'Manage customers, workspaces and workspace keys for CloudSaver.',
  robots: {index: false, follow: false},
};

export default function RootLayout({children}: {children: ReactNode}) {
  return <html lang="en" data-theme="dark" suppressHydrationWarning><body><ThemeProvider><SessionProvider><AppShell>{children}</AppShell></SessionProvider></ThemeProvider></body></html>;
}
