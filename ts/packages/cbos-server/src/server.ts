import { WebSocketServer, WebSocket } from 'ws';
import { v4 as uuid } from 'uuid';
import { SessionStore } from './store.js';
import { ClientMessage, ServerMessage, Session } from './models.js';

interface Client {
  id: string;
  ws: WebSocket;
  subscriptions: Set<string>;
  subscribeAll: boolean;
}

export class CBOSServer {
  private wss: WebSocketServer;
  private clients: Map<string, Client> = new Map();
  private store: SessionStore;

  constructor(port: number = 32205) {
    this.store = new SessionStore();
    this.wss = new WebSocketServer({ port });

    this.wss.on('connection', (ws) => this.handleConnection(ws));
    this.wss.on('error', (err) => console.error('WebSocket server error:', err));

    console.log(`CBOS server listening on ws://localhost:${port}`);
  }

  getStore(): SessionStore {
    return this.store;
  }

  private handleConnection(ws: WebSocket): void {
    const clientId = uuid();
    const client: Client = {
      id: clientId,
      ws,
      subscriptions: new Set(),
      subscribeAll: true, // Subscribe to all by default
    };
    this.clients.set(clientId, client);
    console.log(`Client connected: ${clientId}`);

    // Send initial session list
    this.sendToClient(client, {
      type: 'sessions',
      sessions: this.store.all(),
    });

    ws.on('message', (data) => {
      try {
        const msg = JSON.parse(data.toString()) as ClientMessage;
        this.handleMessage(client, msg);
      } catch (e) {
        this.sendToClient(client, {
          type: 'error',
          message: 'Invalid message format',
        });
      }
    });

    ws.on('close', () => {
      this.clients.delete(clientId);
      console.log(`Client disconnected: ${clientId}`);
    });

    ws.on('error', (err) => {
      console.error(`Client ${clientId} error:`, err);
      this.clients.delete(clientId);
    });
  }

  private handleMessage(client: Client, msg: ClientMessage): void {
    switch (msg.type) {
      case 'subscribe':
        if (msg.sessions.includes('*')) {
          client.subscribeAll = true;
          client.subscriptions.clear();
        } else {
          client.subscribeAll = false;
          client.subscriptions.clear();
          msg.sessions.forEach((s) => client.subscriptions.add(s));
        }
        break;

      case 'create_session':
        try {
          const session = this.store.create(msg.slug, msg.path);
          this.broadcast({ type: 'session_created', session });
          console.log(`Session created: ${msg.slug} at ${msg.path}`);
        } catch (e) {
          this.sendToClient(client, {
            type: 'error',
            message: (e as Error).message,
          });
        }
        break;

      case 'delete_session':
        if (this.store.delete(msg.slug)) {
          this.broadcast({ type: 'session_deleted', slug: msg.slug });
          console.log(`Session deleted: ${msg.slug}`);
        } else {
          this.sendToClient(client, {
            type: 'error',
            message: `Session "${msg.slug}" not found`,
          });
        }
        break;

      case 'list_sessions':
        this.sendToClient(client, {
          type: 'sessions',
          sessions: this.store.all(),
        });
        break;

      case 'send_input':
        // Handled by SessionManager - emit event
        this.emit('send_input', msg.slug, msg.text);
        break;

      case 'interrupt':
        // Handled by SessionManager - emit event
        this.emit('interrupt', msg.slug);
        break;
    }
  }

  private sendToClient(client: Client, msg: ServerMessage): void {
    if (client.ws.readyState === WebSocket.OPEN) {
      client.ws.send(JSON.stringify(msg));
    }
  }

  broadcast(msg: ServerMessage, filterSlug?: string): void {
    for (const client of this.clients.values()) {
      if (filterSlug && !client.subscribeAll && !client.subscriptions.has(filterSlug)) {
        continue;
      }
      this.sendToClient(client, msg);
    }
  }

  // Event emitter pattern for SessionManager integration
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private eventHandlers: Map<string, Array<(...args: any[]) => void>> = new Map();

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  on(event: string, handler: (...args: any[]) => void): void {
    if (!this.eventHandlers.has(event)) {
      this.eventHandlers.set(event, []);
    }
    this.eventHandlers.get(event)!.push(handler);
  }

  private emit(event: string, ...args: unknown[]): void {
    const handlers = this.eventHandlers.get(event) || [];
    for (const handler of handlers) {
      handler(...args);
    }
  }

  // Public methods for external components
  onSessionWaiting(slug: string, context: string): void {
    const session = this.store.update(slug, {
      state: 'waiting',
      lastContext: context,
    });
    if (session) {
      this.broadcast({ type: 'session_update', session }, slug);
      this.broadcast({ type: 'session_waiting', slug, context }, slug);
    }
  }

  updateSession(slug: string, updates: Partial<Session>): void {
    const session = this.store.update(slug, updates);
    if (session) {
      this.broadcast({ type: 'session_update', session }, slug);
    }
  }

  broadcastClaudeEvent(slug: string, event: unknown): void {
    this.broadcast({ type: 'claude_event', slug, event }, slug);
  }

  close(): void {
    this.wss.close();
  }
}
