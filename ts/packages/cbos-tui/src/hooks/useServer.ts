import { useState, useEffect, useCallback, useRef } from 'react';
import WebSocket from 'ws';

// Types (inline to avoid cross-package import issues)
type SessionState = 'idle' | 'thinking' | 'working' | 'waiting' | 'error';

type EventCategory =
  | 'init'
  | 'thinking'
  | 'text'
  | 'tool_use'
  | 'tool_result'
  | 'result'
  | 'error'
  | 'waiting'
  | 'question'
  | 'system'
  | 'compact'
  | 'user_msg'
  | 'unknown';

interface FormattedEvent {
  category: EventCategory;
  timestamp: string;
  summary: string;
  details?: string;
  isActionable: boolean;
  priority: 'low' | 'normal' | 'high' | 'critical';
  toolName?: string;
  toolInput?: string;
  toolOutput?: string;
  cost?: number;
  duration?: number;
  sessionId?: string;
  questionOptions?: string[];
}

interface Session {
  slug: string;
  path: string;
  state: SessionState;
  claudeSessionId?: string;
  createdAt: string;
  lastActivity: string;
  lastContext?: string;
  messageCount: number;
  events: FormattedEvent[];  // Formatted events
}

type ServerMessage =
  | { type: 'sessions'; sessions: Session[] }
  | { type: 'session_update'; session: Session }
  | { type: 'session_waiting'; slug: string; context: string }
  | { type: 'session_created'; session: Session }
  | { type: 'session_deleted'; slug: string }
  | { type: 'claude_event'; slug: string; event: unknown }
  | { type: 'output'; slug: string; data: string }
  | { type: 'formatted_event'; slug: string; event: FormattedEvent }
  | { type: 'error'; message: string };

type ClientMessage =
  | { type: 'subscribe'; sessions: string[] }
  | { type: 'create_session'; slug: string; path: string }
  | { type: 'delete_session'; slug: string }
  | { type: 'send_input'; slug: string; text: string }
  | { type: 'interrupt'; slug: string }
  | { type: 'list_sessions' };

interface UseServerOptions {
  url?: string;
  autoReconnect?: boolean;
}

interface UseServerReturn {
  connected: boolean;
  sessions: Session[];
  error: string | null;
  createSession: (slug: string, path: string) => void;
  deleteSession: (slug: string) => void;
  sendInput: (slug: string, text: string) => void;
  interrupt: (slug: string) => void;
  reconnect: () => void;
}

export function useServer(options: UseServerOptions = {}): UseServerReturn {
  const url = options.url ?? `ws://localhost:${process.env.CBOS_PORT ?? 32205}`;
  const autoReconnect = options.autoReconnect ?? true;

  const [connected, setConnected] = useState(false);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.on('open', () => {
        setConnected(true);
        setError(null);
        // Subscribe to all sessions
        ws.send(JSON.stringify({ type: 'subscribe', sessions: ['*'] }));
      });

      ws.on('message', (data) => {
        try {
          const msg = JSON.parse(data.toString()) as ServerMessage;
          handleMessage(msg);
        } catch {
          // Ignore parse errors
        }
      });

      ws.on('close', () => {
        setConnected(false);
        wsRef.current = null;

        if (autoReconnect) {
          reconnectTimeoutRef.current = setTimeout(connect, 2000);
        }
      });

      ws.on('error', (err) => {
        setError(`Connection error: ${err.message}`);
        setConnected(false);
      });
    } catch (e) {
      setError(`Failed to connect: ${(e as Error).message}`);
    }
  }, [url, autoReconnect]);

  const handleMessage = useCallback((msg: ServerMessage) => {
    switch (msg.type) {
      case 'sessions':
        // Preserve existing events when updating sessions (server doesn't send events)
        setSessions((prev) => {
          const prevEventsMap = new Map(prev.map((s) => [s.slug, s.events || []]));
          return msg.sessions.map((s) => ({
            ...s,
            events: s.events || prevEventsMap.get(s.slug) || [],
          }));
        });
        break;

      case 'session_created':
        setSessions((prev) => [...prev, { ...msg.session, events: [] }]);
        break;

      case 'session_deleted':
        setSessions((prev) => prev.filter((s) => s.slug !== msg.slug));
        break;

      case 'session_update':
        // Preserve existing events when updating session metadata
        setSessions((prev) =>
          prev.map((s) =>
            s.slug === msg.session.slug
              ? { ...msg.session, events: msg.session.events || s.events || [] }
              : s
          )
        );
        break;

      case 'session_waiting':
        setSessions((prev) =>
          prev.map((s) =>
            s.slug === msg.slug
              ? { ...s, state: 'waiting' as SessionState, lastContext: msg.context }
              : s
          )
        );
        break;

      case 'output':
        // Raw output - deprecated, use formatted_event instead
        break;

      case 'formatted_event':
        // Add formatted event to session (with deduplication)
        setSessions((prev) =>
          prev.map((s) => {
            if (s.slug !== msg.slug) return s;

            const existingEvents = s.events || [];
            const lastEvent = existingEvents.at(-1);

            // Skip duplicate events (same category and summary)
            if (
              lastEvent &&
              lastEvent.category === msg.event.category &&
              lastEvent.summary === msg.event.summary
            ) {
              return s;
            }

            return {
              ...s,
              events: [...existingEvents, msg.event].slice(-100), // Keep last 100 events
            };
          })
        );
        break;

      case 'error':
        setError(msg.message);
        break;
    }
  }, []);

  useEffect(() => {
    connect();

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      wsRef.current?.close();
    };
  }, [connect]);

  const send = useCallback((msg: ClientMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  }, []);

  const createSession = useCallback(
    (slug: string, path: string) => {
      send({ type: 'create_session', slug, path });
    },
    [send]
  );

  const deleteSession = useCallback(
    (slug: string) => {
      send({ type: 'delete_session', slug });
    },
    [send]
  );

  const sendInput = useCallback(
    (slug: string, text: string) => {
      send({ type: 'send_input', slug, text });
    },
    [send]
  );

  const interrupt = useCallback(
    (slug: string) => {
      send({ type: 'interrupt', slug });
    },
    [send]
  );

  const reconnect = useCallback(() => {
    wsRef.current?.close();
    connect();
  }, [connect]);

  return {
    connected,
    sessions,
    error,
    createSession,
    deleteSession,
    sendInput,
    interrupt,
    reconnect,
  };
}

export type { Session, SessionState, FormattedEvent, EventCategory };
