import type { Metadata } from 'next';
import '@fontsource-variable/inter';
import '@fontsource-variable/jetbrains-mono';
import './globals.css';
import './console-theme.css';
import './experience.css';
import {ThemeProvider} from '../components/ThemeProvider';
import {WorkspaceProvider} from '../components/WorkspaceProvider';
import {AppShell} from '../components/AppShell';
export const dynamic='force-dynamic';
export const metadata: Metadata = { title: 'CloudSaver | Multi-cloud FinOps workspace', description: 'Understand cloud resource signals, review cost evidence, and govern change in one isolated workspace.' };
export default function RootLayout({children}:{children:React.ReactNode}) {return <html lang="en" data-theme="dark" suppressHydrationWarning><body><ThemeProvider><WorkspaceProvider><AppShell>{children}</AppShell></WorkspaceProvider></ThemeProvider></body></html>;}
