'use client';

import { useEffect, useState, useCallback } from 'react';
import LoadingSpinner from '@/components/common/LoadingSpinner';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const API_KEY = process.env.NEXT_PUBLIC_API_KEY || '';

interface NewsletterData {
  content: string | null;
  generated_at: string | null;
  status: string;
}

export default function NewsletterPage() {
  const [newsletter, setNewsletter] = useState<NewsletterData | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchNewsletter = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/newsletter/latest`, {
        headers: { 'X-API-Key': API_KEY },
      });
      if (!res.ok) throw new Error(`API ${res.status}`);
      const data: NewsletterData = await res.json();
      setNewsletter(data);

      if (data.status === 'generating') {
        setGenerating(true);
        setTimeout(fetchNewsletter, 5000);
      } else {
        setGenerating(false);
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchNewsletter();
  }, [fetchNewsletter]);

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/newsletter/generate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': API_KEY,
        },
      });
      if (!res.ok) throw new Error(`API ${res.status}`);

      // Poll for completion
      const poll = async () => {
        const pollRes = await fetch(`${API_URL}/newsletter/latest`, {
          headers: { 'X-API-Key': API_KEY },
        });
        if (!pollRes.ok) return;
        const data: NewsletterData = await pollRes.json();
        setNewsletter(data);
        if (data.status === 'generating') {
          setTimeout(poll, 5000);
        } else {
          setGenerating(false);
        }
      };
      setTimeout(poll, 5000);
    } catch (e: any) {
      setError(e.message);
      setGenerating(false);
    }
  };

  // Simple markdown to HTML renderer
  const renderMarkdown = (md: string) => {
    let html = md
      // Headers
      .replace(/^### (.+)$/gm, '<h3 class="text-base font-semibold text-slate-200 mt-6 mb-2">$1</h3>')
      .replace(/^## (.+)$/gm, '<h2 class="text-lg font-bold text-slate-100 mt-8 mb-3 pb-2 border-b border-slate-700/50">$1</h2>')
      .replace(/^# (.+)$/gm, '<h1 class="text-xl font-bold text-slate-50 mt-4 mb-4">$1</h1>')
      // Bold and italic
      .replace(/\*\*(.+?)\*\*/g, '<strong class="text-slate-200 font-semibold">$1</strong>')
      .replace(/\*(.+?)\*/g, '<em class="text-slate-300 italic">$1</em>')
      // Lists
      .replace(/^- (.+)$/gm, '<li class="text-slate-300 ml-4 mb-1">$1</li>')
      .replace(/^(\d+)\. (.+)$/gm, '<li class="text-slate-300 ml-4 mb-1">$2</li>')
      // Paragraphs (lines not starting with < that have content)
      .replace(/^(?!<)(.+)$/gm, (match) => {
        if (match.trim() === '') return '';
        return `<p class="text-sm text-slate-300 leading-relaxed mb-3">${match}</p>`;
      });

    // Wrap consecutive <li> tags in <ul>
    html = html.replace(
      /(<li[^>]*>.*?<\/li>\n?)+/g,
      (match) => `<ul class="list-disc mb-4">${match}</ul>`
    );

    return html;
  };

  if (loading) return <LoadingSpinner text="Loading newsletter..." />;

  return (
    <div className="space-y-6 animate-fadeIn max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Intelligence Brief</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Daily synthesis by the Master Strategist
          </p>
        </div>
        <div className="flex items-center gap-3">
          {newsletter?.generated_at && (
            <span className="text-[10px] text-slate-600">
              Generated: {new Date(newsletter.generated_at).toLocaleString()}
            </span>
          )}
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="text-xs px-4 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {generating ? 'Generating...' : 'Generate Newsletter'}
          </button>
        </div>
      </div>

      {/* Generating indicator */}
      {generating && (
        <div className="bg-blue-500/10 border border-blue-500/20 rounded-xl p-6 text-center">
          <div className="inline-block animate-spin text-blue-400 text-xl mb-2">&#x25E0;</div>
          <p className="text-sm text-blue-300">
            The Master Strategist is synthesizing today&apos;s intelligence...
          </p>
          <p className="text-xs text-slate-500 mt-1">This typically takes 30-60 seconds.</p>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4">
          <p className="text-sm text-red-400">{error}</p>
        </div>
      )}

      {/* Newsletter content */}
      {newsletter?.content && !generating && (
        <div className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-8">
          <div
            className="newsletter-content"
            dangerouslySetInnerHTML={{ __html: renderMarkdown(newsletter.content) }}
          />
        </div>
      )}

      {/* Empty state */}
      {(!newsletter?.content && !generating && !error) && (
        <div className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-12 text-center">
          <p className="text-2xl mb-3">&#x1F4F0;</p>
          <p className="text-sm text-slate-400 mb-4">
            No newsletter generated yet. Run the pipeline first to ingest data and generate predictions, then click &quot;Generate Newsletter&quot; for the Master Strategist&apos;s daily synthesis.
          </p>
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="text-xs px-4 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-500 transition-colors"
          >
            Generate Newsletter
          </button>
        </div>
      )}
    </div>
  );
}
