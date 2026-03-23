'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import { createChatWebSocket } from '@/lib/api';

interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
}

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [typing, setTyping] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    setConnecting(true);
    const ws = createChatWebSocket();
    if (!ws) {
      setConnecting(false);
      setMessages((prev) => [
        ...prev,
        { role: 'system', content: 'Failed to create WebSocket connection. Check API URL.', timestamp: new Date() },
      ]);
      return;
    }

    ws.onopen = () => {
      setConnected(true);
      setConnecting(false);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setTyping(false);
        if (data.type === 'message') {
          setMessages((prev) => [
            ...prev,
            { role: 'assistant', content: data.content, timestamp: new Date() },
          ]);
        } else if (data.type === 'error') {
          setMessages((prev) => [
            ...prev,
            { role: 'system', content: data.content, timestamp: new Date() },
          ]);
        }
      } catch {
        setTyping(false);
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', content: event.data, timestamp: new Date() },
        ]);
      }
    };

    ws.onclose = () => {
      setConnected(false);
      setConnecting(false);
      setTyping(false);
    };

    ws.onerror = () => {
      setConnected(false);
      setConnecting(false);
      setTyping(false);
    };

    wsRef.current = ws;
  }, []);

  useEffect(() => {
    connect();
    return () => {
      wsRef.current?.close();
    };
  }, [connect]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, typing]);

  const send = () => {
    const text = input.trim();
    if (!text || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

    setMessages((prev) => [
      ...prev,
      { role: 'user', content: text, timestamp: new Date() },
    ]);
    setInput('');
    setTyping(true);

    try {
      wsRef.current.send(JSON.stringify({ message: text }));
    } catch {
      setTyping(false);
      setMessages((prev) => [
        ...prev,
        { role: 'system', content: 'Failed to send message.', timestamp: new Date() },
      ]);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div className="flex flex-col h-[calc(100vh-48px)] animate-fadeIn">
      {/* Header */}
      <div className="flex items-center justify-between pb-4">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Chat</h1>
          <p className="text-xs text-slate-500 mt-0.5">Interactive analyst queries via Claude</p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`h-2 w-2 rounded-full ${
              connected ? 'bg-emerald-500' : connecting ? 'bg-amber-500 animate-pulse' : 'bg-red-500'
            }`}
          />
          <span className="text-xs text-slate-500">
            {connected ? 'Connected' : connecting ? 'Connecting...' : 'Disconnected'}
          </span>
          {!connected && !connecting && (
            <button
              onClick={connect}
              className="text-xs text-blue-400 hover:text-blue-300 ml-2 transition-colors"
            >
              Reconnect
            </button>
          )}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto bg-surface-700/30 border border-slate-700/50 rounded-xl p-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-slate-500">
            <p className="text-sm mb-1">No messages yet</p>
            <p className="text-xs">Ask about predictions, agents, signals, or system status</p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[70%] rounded-xl px-4 py-3 text-sm ${
                msg.role === 'user'
                  ? 'bg-blue-500/20 text-slate-200'
                  : msg.role === 'system'
                  ? 'bg-red-500/10 text-red-400 border border-red-500/20'
                  : 'bg-surface-600/80 text-slate-300 border border-slate-700/50'
              }`}
            >
              <p className="whitespace-pre-wrap leading-relaxed">{msg.content}</p>
              <p className="text-[10px] mt-1.5 opacity-40">
                {msg.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </p>
            </div>
          </div>
        ))}
        {typing && (
          <div className="flex justify-start">
            <div className="bg-surface-600/80 border border-slate-700/50 rounded-xl px-4 py-3">
              <div className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="pt-3 flex items-end gap-3">
        <textarea
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={connected ? 'Type a message... (Enter to send, Shift+Enter for newline)' : 'Connect to start chatting...'}
          disabled={!connected}
          rows={1}
          className="flex-1 bg-surface-700 border border-slate-700/50 rounded-xl px-4 py-3 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-blue-500/50 resize-none disabled:opacity-40 transition-colors"
        />
        <button
          onClick={send}
          disabled={!connected || !input.trim()}
          className="px-5 py-3 rounded-xl bg-blue-500/20 text-blue-400 text-sm font-medium hover:bg-blue-500/30 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          Send
        </button>
      </div>
    </div>
  );
}
