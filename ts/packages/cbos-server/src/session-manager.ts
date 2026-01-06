import * as pty from 'node-pty';
import { EventEmitter } from 'events';
import { SessionStore } from './store.js';
import { SessionState } from './models.js';

interface RunningSession {
  slug: string;
  pty: pty.IPty;
  claudeSessionId?: string;
}

export interface SessionManagerEvents {
  state_change: (slug: string, state: SessionState) => void;
  claude_event: (slug: string, event: unknown) => void;
  process_end: (slug: string, code: number | null) => void;
  output: (slug: string, data: string) => void;
}

export class SessionManager extends EventEmitter {
  private store: SessionStore;
  private running: Map<string, RunningSession> = new Map();
  private claudeCommand: string;

  constructor(store: SessionStore, claudeCommand: string = 'claude') {
    super();
    this.store = store;
    this.claudeCommand = claudeCommand;
  }

  async invoke(slug: string, prompt: string): Promise<void> {
    const session = this.store.get(slug);
    if (!session) {
      throw new Error(`Session "${slug}" not found`);
    }

    if (this.running.has(slug)) {
      throw new Error(`Session "${slug}" is already running`);
    }

    const args = [
      '-p', prompt,
      '--output-format', 'stream-json',
      '--verbose',
      '--dangerously-skip-permissions',
    ];

    // Resume existing session if we have a Claude session ID
    if (session.claudeSessionId) {
      args.push('--resume', session.claudeSessionId);
    }

    console.log(`Starting Claude for ${slug}: ${this.claudeCommand} ${args.join(' ')}`);

    // Use node-pty to spawn with a pseudo-terminal (Claude requires TTY)
    const proc = pty.spawn(this.claudeCommand, args, {
      name: 'xterm-256color',
      cols: 120,
      rows: 30,
      cwd: session.path,
      env: {
        ...process.env,
        NO_COLOR: '1',
      } as { [key: string]: string },
    });

    this.running.set(slug, { slug, pty: proc });
    this.store.update(slug, { state: 'working' });
    this.emit('state_change', slug, 'working');

    let buffer = '';

    proc.onData((data: string) => {
      console.log(`[${slug}] output (${data.length} bytes):`, data.slice(0, 100));
      this.emit('output', slug, data);

      buffer += data;
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';

      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const event = JSON.parse(line);
          this.handleClaudeEvent(slug, event);
        } catch {
          // Non-JSON output, might be status messages
        }
      }
    });

    proc.onExit(({ exitCode }) => {
      this.running.delete(slug);
      const newState: SessionState = exitCode === 0 ? 'idle' : 'error';
      this.store.update(slug, { state: newState });
      this.emit('state_change', slug, newState);
      this.emit('process_end', slug, exitCode);
      console.log(`Claude process for ${slug} exited with code ${exitCode}`);
    });
  }

  private handleClaudeEvent(slug: string, event: Record<string, unknown>): void {
    // Extract session ID from init event
    if (event.type === 'init' && typeof event.session_id === 'string') {
      const session = this.store.get(slug);
      if (session && !session.claudeSessionId) {
        this.store.update(slug, { claudeSessionId: event.session_id });
        console.log(`Session ${slug} linked to Claude session ${event.session_id}`);
      }
    }

    // Update state based on event type
    if (event.type === 'assistant') {
      // Claude is generating response
      const session = this.store.get(slug);
      if (session) {
        this.store.update(slug, {
          state: 'thinking',
          messageCount: session.messageCount + 1,
        });
        this.emit('state_change', slug, 'thinking');
      }
    }

    if (event.type === 'tool_use') {
      // Claude is using a tool
      this.store.update(slug, { state: 'working' });
      this.emit('state_change', slug, 'working');
    }

    // Emit event for broadcasting
    this.emit('claude_event', slug, event);
  }

  interrupt(slug: string): boolean {
    const running = this.running.get(slug);
    if (!running) {
      return false;
    }

    console.log(`Interrupting session ${slug}`);
    running.pty.kill();
    return true;
  }

  isRunning(slug: string): boolean {
    return this.running.has(slug);
  }

  getRunningCount(): number {
    return this.running.size;
  }

  // Send input to pty
  sendStdin(slug: string, text: string): boolean {
    const running = this.running.get(slug);
    if (!running) {
      return false;
    }

    running.pty.write(text + '\n');
    return true;
  }
}
