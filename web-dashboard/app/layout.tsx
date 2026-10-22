import type { Metadata } from 'next';
import '@fontsource-variable/inter';
import '@fontsource-variable/jetbrains-mono';
import './globals.css';
import {WorkspaceProvider} from '../components/WorkspaceProvider';
import {AppShell} from '../components/AppShell';
export const metadata: Metadata = { title: 'CloudSaver | Multi-cloud FinOps workspace', description: 'Understand cloud resource signals, review cost evidence, and govern change in one tenant-scoped workspace.' };
export default function RootLayout({children}:{children:React.ReactNode}) {return <html lang="en"><body><WorkspaceProvider><AppShell>{children}</AppShell></WorkspaceProvider></body></html>;}
