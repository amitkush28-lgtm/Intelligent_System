'use client';

import { useEffect, useState } from 'react';
import { getAgents } from '@/lib/api';
import { AgentMetrics } from '@/lib/types';
import AgentCard from '@/components/agents/AgentCard';
import LoadingSpinner from '@/components/common/LoadingSpinner';

export default function AgentsPage() {
  const [agents, setAgents] = useState<AgentMetrics[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const data = await getAgents();
        setAgents(data.agents);
      } catch (e: any) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) return <LoadingSpinner text="Loading agents..." />;
  if (error)
    return <div className="py-20 text-center text-sm text-red-400">{error}</div>;

  return (
    <div className="space-y-5 animate-fadeIn">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">Agents</h1>
        <p className="text-xs text-slate-500 mt-0.5">
          6 specialist agents with performance metrics
        </p>
      </div>
      <div className="grid grid-cols-3 gap-4">
        {agents.map((a) => (
          <AgentCard key={a.agent} agent={a} />
        ))}
      </div>
    </div>
  );
}
