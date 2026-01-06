import { useState, useEffect, useCallback, useRef } from 'react';
import WebSocket from 'ws';

// Types (inline to avoid cross-package import issues)
type SessionState = 'idle' | 'thinking' | 'working' | 'waiting' | 'error';

interface Session {
  slug: string;
  path: string;
  state: SessionState;
  claudeSessionId?: string;
  createdAt: string;
  lastActivity: string;
  lastContext?: string;
  messageCount: number;
  buffer?: string;  // Streaming output buffer
}

type ServerMessage =
  | { type: 'sessions'; sessions: Session[] }
  | { type: 'session_update'; session: Session }
  | { type: 'session_waiting'; slug: string; context: string }
  | { type: 'session_created'; session: Session }
  | { type: 'session_deleted'; slug: string }
  | { type: 'claude_event'; slug: string; event: unknown }
  | { type: 'output'; slug: string; data: string }
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
        setSessions(msg.sessions);
        break;

      case 'session_created':
        setSessions((prev) => [...prev, msg.session]);
        break;

      case 'session_deleted':
        setSessions((prev) => prev.filter((s) => s.slug !== msg.slug));
        break;

      case 'session_update':
        setSessions((prev) =>
          prev.map((s) => (s.slug === msg.session.slug ? msg.session : s))
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
        // Append output to session buffer
        setSessions((prev) =>
          prev.map((s) =>
            s.slug === msg.slug
              ? { ...s, buffer: (s.buffer ?? '') + msg.data }
              : s
          )
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

export type { Session, SessionState };
