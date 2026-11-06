import type { Metadata } from 'next';
import '@fontsource-variable/geist';
import '@fontsource-variable/jetbrains-mono';
import './globals.css';
import './console-theme.css';
import './experience.css';
import './theme-tokens.css';
import './theme-surfaces.css';
import './theme-preset-dark.css';
import './workspace-tabs.css';
import './login-surfaces.css';
import './theme-atlas.css';
import './console-polish.css';
import {ThemeProvider} from '../components/ThemeProvider';
import {WorkspaceProvider} from '../components/WorkspaceProvider';
import {AppShell} from '../components/AppShell';
export const dynamic='force-dynamic';
export const metadata: Metadata = { title: 'CloudSaver | Multi-cloud FinOps workspace', description: 'Understand cloud resource signals, review cost evidence, and govern change in one isolated workspace.' };
export default function RootLayout({children}:{children:React.ReactNode}) {return <html lang="en" data-theme="dark" data-ui-preset="atlas" data-ui-surface="flat" suppressHydrationWarning><body><ThemeProvider><WorkspaceProvider><AppShell>{children}</AppShell></WorkspaceProvider></ThemeProvider></body></html>;}
