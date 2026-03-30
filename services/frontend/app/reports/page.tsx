'use client';

import { useEffect, useState, useCallback } from 'react';
import LoadingSpinner from '@/components/common/LoadingSpinner';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const API_KEY = process.env.NEXT_PUBLIC_API_KEY || '';

interface ReportStatus {
  status: 'empty' | 'generating' | 'ready';
  generated_at?: string;
}

interface NewsletterCadence {
  type: 'weekly' | 'monthly' | 'yearly';
  title: string;
  description: string;
}

interface ThematicReport {
  id: string;
  name: string;
  icon: string;
  description: string;
  apiType: string;
  pdfSource: string;
}

const NEWSLETTER_CADENCES: NewsletterCadence[] = [
  {
    type: 'weekly',
    title: 'Weekly Intelligence Brief',
    description: 'Key developments, strategic shifts, and emerging patterns across all domains',
  },
  {
    type: 'monthly',
    title: 'Monthly Strategic Review',
    description: 'Deeper analysis of month-long trends and their implications',
  },
  {
    type: 'yearly',
    title: 'Annual Intelligence Report',
    description: 'Comprehensive year-in-review with predictions for the year ahead',
  },
];

const THEMATIC_REPORTS: ThematicReport[] = [
  {
    id: 'geopolitics',
    name: 'Geopolitics & Security',
    icon: '🌍',
    description: 'International relations, conflicts, and strategic alliances',
    apiType: 'geopolitics_security',
    pdfSource: 'geopolitics_security',
  },
  {
    id: 'economy',
    name: 'Economy & Markets',
    icon: '💹',
    description: 'Economic trends, financial markets, and trade dynamics',
    apiType: 'economy_markets',
    pdfSource: 'economy_markets',
  },
  {
    id: 'technology',
    name: 'Technology & AI',
    icon: '🤖',
    description: 'Breakthrough innovations, AI developments, and tech disruption',
    apiType: 'technology_ai',
    pdfSource: 'technology_ai',
  },
  {
    id: 'governance',
    name: 'Political Risk',
    icon: '⚖️',
    description: 'Policy changes, regulatory shifts, and governance risks',
    apiType: 'political_risk',
    pdfSource: 'political_risk',
  },
  {
    id: 'climate',
    name: 'Energy & Climate',
    icon: '🌱',
    description: 'Environmental changes, energy markets, and resource scarcity',
    apiType: 'energy_climate',
    pdfSource: 'energy_climate',
  },
  {
    id: 'trade',
    name: 'Trade & Supply Chains',
    icon: '📦',
    description: 'Global commerce, logistics, and economic sanctions',
    apiType: 'trade_supply_chains',
    pdfSource: 'trade_supply_chains',
  },
];

export default function ReportsPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newsletterStatuses, setNewsletterStatuses] = useState<Record<string, ReportStatus>>({});
  const [reportStatuses, setReportStatuses] = useState<Record<string, ReportStatus>>({});
  const [outlookStatus, setOutlookStatus] = useState<ReportStatus>({ status: 'empty' });
  const [generatingId, setGeneratingId] = useState<string | null>(null);

  // Fetch initial statuses
  useEffect(() => {
    fetchAllStatuses();
  }, []);

  const fetchAllStatuses = useCallback(async () => {
    try {
      setLoading(true);
      // In a real implementation, you'd fetch the actual status from the API
      // For now, initialize with empty status
      const newsletters: Record<string, ReportStatus> = {};
      NEWSLETTER_CADENCES.forEach((c) => {
        newsletters[c.type] = { status: 'empty' };
      });
      setNewsletterStatuses(newsletters);

      const reports: Record<string, ReportStatus> = {};
      THEMATIC_REPORTS.forEach((r) => {
        reports[r.id] = { status: 'empty' };
      });
      setReportStatuses(reports);

      setOutlookStatus({ status: 'empty' });
      setError(null);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleGenerateNewsletter = async (cadence: string) => {
    setGeneratingId(`newsletter_${cadence}`);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/newsletter/generate?cadence=${cadence}`, {
        method: 'POST',
        headers: {
          'X-API-Key': API_KEY,
        },
      });
      if (!res.ok) throw new Error(`API ${res.status}`);

      setNewsletterStatuses((prev) => ({
        ...prev,
        [cadence]: { status: 'generating' },
      }));
      pollStatus(`newsletter_${cadence}`, cadence, 'newsletter');
    } catch (e: any) {
      setError(e.message);
      setGeneratingId(null);
    }
  };

  const handleGenerateReport = async (reportId: string, apiType: string) => {
    setGeneratingId(`report_${reportId}`);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/reports/generate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': API_KEY,
        },
        body: JSON.stringify({ theme: apiType }),
      });
      if (!res.ok) throw new Error(`API ${res.status}`);

      setReportStatuses((prev) => ({
        ...prev,
        [reportId]: { status: 'generating' },
      }));
      pollStatus(`report_${reportId}`, apiType, 'report');
    } catch (e: any) {
      setError(e.message);
      setGeneratingId(null);
    }
  };

  const handleGenerateOutlook = async () => {
    setGeneratingId('outlook');
    setError(null);
    try {
      const res = await fetch(`${API_URL}/reports/generate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': API_KEY,
        },
        body: JSON.stringify({ theme: 'twelve_month_outlook' }),
      });
      if (!res.ok) throw new Error(`API ${res.status}`);

      setOutlookStatus({ status: 'generating' });
      pollStatus('outlook', 'twelve_month_outlook', 'report');
    } catch (e: any) {
      setError(e.message);
      setGeneratingId(null);
    }
  };

  const pollStatus = (uiId: string, apiKey: string, source: 'report' | 'newsletter') => {
    const interval = setInterval(async () => {
      try {
        const endpoint = source === 'newsletter'
          ? `${API_URL}/newsletter/latest?cadence=${apiKey}`
          : `${API_URL}/reports/latest?type=${apiKey}`;

        const res = await fetch(endpoint, {
          headers: { 'X-API-Key': API_KEY },
        });
        if (!res.ok) return;

        const data = await res.json();

        if (data.status === 'ready') {
          clearInterval(interval);
          const readyStatus: ReportStatus = {
            status: 'ready',
            generated_at: data.generated_at || new Date().toISOString(),
          };

          if (uiId.startsWith('newsletter_')) {
            setNewsletterStatuses((prev) => ({ ...prev, [apiKey]: readyStatus }));
          } else if (uiId === 'outlook') {
            setOutlookStatus(readyStatus);
          } else if (uiId.startsWith('report_')) {
            const reportId = uiId.replace('report_', '');
            setReportStatuses((prev) => ({ ...prev, [reportId]: readyStatus }));
          }
          setGeneratingId(null);
        } else if (data.status !== 'generating') {
          // Failed or unexpected status
          clearInterval(interval);
          setGeneratingId(null);
        }
      } catch {
        // Keep polling on network errors
      }
    }, 5000);

    // Safety: stop polling after 5 minutes
    setTimeout(() => {
      clearInterval(interval);
      setGeneratingId(null);
    }, 300000);
  };

  const handleDownloadPDF = async (typeKey: string, source: 'report' | 'newsletter', filename: string) => {
    try {
      const res = await fetch(`${API_URL}/reports/pdf?type=${typeKey}&source=${source}`, {
        headers: { 'X-API-Key': API_KEY },
      });
      if (!res.ok) throw new Error(`API ${res.status}`);

      const blob = await res.blob();
      const downloadUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = downloadUrl;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(downloadUrl);
    } catch (e: any) {
      setError(e.message);
    }
  };

  const getStatusDisplay = (status: ReportStatus) => {
    if (status.status === 'generating') {
      return (
        <div className="flex items-center gap-2 text-sm text-blue-400">
          <span className="inline-block animate-spin">⟳</span>
          Generating...
        </div>
      );
    }
    if (status.status === 'ready' && status.generated_at) {
      return (
        <div className="flex items-center gap-2 text-sm text-emerald-400">
          <span>✓</span>
          Ready • {new Date(status.generated_at).toLocaleDateString()}
        </div>
      );
    }
    return <div className="text-sm text-slate-500">Not generated</div>;
  };

  if (loading) return <LoadingSpinner text="Loading reports..." />;

  return (
    <div className="space-y-8 animate-fadeIn">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold text-slate-100">Reports & Analysis</h1>
        <p className="text-sm text-slate-400 mt-1">
          Generate intelligence briefings, thematic deep-dives, and strategic outlooks
        </p>
      </div>

      {/* Error message */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4">
          <p className="text-sm text-red-400">{error}</p>
        </div>
      )}

      {/* Section 1: Intelligence Newsletters */}
      <div>
        <h2 className="text-lg font-semibold text-slate-200 mb-4 flex items-center gap-2">
          <span>📰</span> Intelligence Newsletters
        </h2>
        <div className="grid grid-cols-3 gap-4">
          {NEWSLETTER_CADENCES.map((cadence) => {
            const status = newsletterStatuses[cadence.type];
            const isGenerating = generatingId === `newsletter_${cadence.type}`;
            return (
              <div
                key={cadence.type}
                className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-6 hover:border-slate-700 transition-colors"
              >
                <h3 className="text-base font-semibold text-slate-100 mb-1">{cadence.title}</h3>
                <p className="text-xs text-slate-400 mb-4">{cadence.description}</p>

                {status && (
                  <div className="mb-4 pb-4 border-b border-slate-700/30">
                    {getStatusDisplay(status)}
                  </div>
                )}

                <div className="flex gap-2">
                  <button
                    onClick={() => handleGenerateNewsletter(cadence.type)}
                    disabled={isGenerating || generatingId !== null}
                    className="flex-1 text-xs px-3 py-2.5 rounded-lg bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-medium"
                  >
                    {isGenerating ? 'Generating...' : 'Generate'}
                  </button>
                  <button
                    onClick={() =>
                      handleDownloadPDF(
                        cadence.type,
                        'newsletter',
                        `intelligence-brief-${cadence.type}.pdf`
                      )
                    }
                    disabled={!status || status.status !== 'ready'}
                    className="flex-1 text-xs px-3 py-2.5 rounded-lg bg-teal-600 text-white hover:bg-teal-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-medium"
                  >
                    Download PDF
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Section 2: 12-Month Outlook */}
      <div>
        <h2 className="text-lg font-semibold text-slate-200 mb-4 flex items-center gap-2">
          <span>🔮</span> 12-Month Outlook
        </h2>
        <div className="bg-gradient-to-br from-indigo-600/20 to-blue-600/20 border border-indigo-500/30 rounded-xl p-8">
          <div className="flex items-start justify-between gap-6">
            <div className="flex-1">
              <h3 className="text-xl font-semibold text-slate-100 mb-2">
                12-Month Outlook: What's Coming
              </h3>
              <p className="text-sm text-slate-300 leading-relaxed">
                System's highest-confidence predictions for the next year, organized by impact on your
                life. Covers geopolitical shifts, economic trends, technological breakthroughs, and
                strategic risks.
              </p>
              {outlookStatus && (
                <div className="mt-4">
                  {getStatusDisplay(outlookStatus)}
                </div>
              )}
            </div>
            <div className="flex flex-col gap-2">
              <button
                onClick={handleGenerateOutlook}
                disabled={generatingId === 'outlook' || generatingId !== null}
                className="text-xs px-6 py-3 rounded-lg bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-medium whitespace-nowrap"
              >
                {generatingId === 'outlook' ? 'Generating...' : 'Generate Outlook'}
              </button>
              <button
                onClick={() =>
                  handleDownloadPDF('twelve_month_outlook', 'report', '12-month-outlook.pdf')
                }
                disabled={!outlookStatus || outlookStatus.status !== 'ready'}
                className="text-xs px-6 py-3 rounded-lg bg-teal-600 text-white hover:bg-teal-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-medium whitespace-nowrap"
              >
                Download PDF
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Section 3: Thematic Deep-Dive Reports */}
      <div>
        <h2 className="text-lg font-semibold text-slate-200 mb-4 flex items-center gap-2">
          <span>📊</span> Thematic Deep-Dive Reports
        </h2>
        <div className="grid grid-cols-2 gap-4">
          {THEMATIC_REPORTS.map((report) => {
            const status = reportStatuses[report.id];
            const isGenerating = generatingId === `report_${report.id}`;
            return (
              <div
                key={report.id}
                className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-6 hover:border-slate-700 transition-colors"
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-start gap-3 flex-1">
                    <span className="text-3xl">{report.icon}</span>
                    <div>
                      <h3 className="text-base font-semibold text-slate-100">{report.name}</h3>
                      <p className="text-xs text-slate-400 mt-1">{report.description}</p>
                    </div>
                  </div>
                </div>

                {status && (
                  <div className="mb-4 pb-4 border-b border-slate-700/30">
                    {getStatusDisplay(status)}
                  </div>
                )}

                <div className="flex gap-2">
                  <button
                    onClick={() => handleGenerateReport(report.id, report.apiType)}
                    disabled={isGenerating || generatingId !== null}
                    className="flex-1 text-xs px-3 py-2.5 rounded-lg bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-medium"
                  >
                    {isGenerating ? 'Generating...' : 'Generate Report'}
                  </button>
                  <button
                    onClick={() =>
                      handleDownloadPDF(
                        report.pdfSource,
                        'report',
                        `report-${report.id}.pdf`
                      )
                    }
                    disabled={!status || status.status !== 'ready'}
                    className="flex-1 text-xs px-3 py-2.5 rounded-lg bg-teal-600 text-white hover:bg-teal-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-medium"
                  >
                    Download PDF
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
