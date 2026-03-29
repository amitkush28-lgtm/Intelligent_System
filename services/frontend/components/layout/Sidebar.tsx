'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const NAV_ITEMS = [
  { href: '/', label: 'Dashboard', icon: '\u2302' },
  { href: '/newsletter', label: 'Newsletter', icon: '\uD83D\uDCF0' },
  { href: '/predictions', label: 'Predictions', icon: '\u25CE' },
  { href: '/agents', label: 'Agents', icon: '\u2726' },
  { href: '/debates', label: 'Debates', icon: '\u2694' },
  { href: '/questions', label: 'Questions', icon: '\u2753' },
  { href: '/signals', label: 'Signals', icon: '\u26A0' },
  { href: '/decisions', label: 'Decisions', icon: '\u2691' },
  { href: '/chat', label: 'Chat', icon: '\u2709' },
];

export default function Sidebar() {
  const pathname = usePathname();

  function isActive(href: string) {
    if (href === '/') return pathname === '/';
    return pathname.startsWith(href);
  }

  return (
    <aside className="fixed top-0 left-0 h-screen w-56 bg-surface-800 border-r border-slate-800/80 flex flex-col z-40">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-slate-800/80">
        <div className="flex items-center gap-2.5">
          <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center text-white text-sm font-bold">
            IS
          </div>
          <div>
            <h1 className="text-sm font-semibold text-slate-200 leading-tight">Intelligence</h1>
            <p className="text-[10px] text-slate-500 uppercase tracking-widest">System</p>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 py-4 px-3 space-y-0.5 overflow-y-auto">
        {NAV_ITEMS.map((item) => {
          const active = isActive(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all ${
                active
                  ? 'bg-blue-500/10 text-blue-400 font-medium'
                  : 'text-slate-400 hover:bg-surface-700 hover:text-slate-200'
              }`}
            >
              <span className="text-base w-5 text-center opacity-70">{item.icon}</span>
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="px-5 py-4 border-t border-slate-800/80">
        <p className="text-[10px] text-slate-600 uppercase tracking-widest">v1.1 &middot; Phase 8</p>
      </div>
    </aside>
  );
}
