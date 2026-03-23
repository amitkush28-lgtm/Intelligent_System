import type { Metadata } from 'next';
import './globals.css';
import Sidebar from '@/components/layout/Sidebar';

export const metadata: Metadata = {
  title: 'Intelligence System',
  description: 'Multi-Agent Intelligence Prediction Dashboard',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="bg-surface-900 text-slate-200 min-h-screen bg-grid">
        <Sidebar />
        <main className="pl-56 min-h-screen">
          <div className="max-w-[1400px] mx-auto px-6 py-6">
            {children}
          </div>
        </main>
      </body>
    </html>
  );
}
