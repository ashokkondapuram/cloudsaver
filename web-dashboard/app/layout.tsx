import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = { title: 'CloudSaver | Azure cost intelligence', description: 'Review Azure waste findings and scan history in one secure workspace.' };
export default function RootLayout({children}:{children:React.ReactNode}) {return <html lang="en"><body>{children}</body></html>;}
