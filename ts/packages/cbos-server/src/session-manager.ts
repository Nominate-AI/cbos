import * as pty from 'node-pty';
import { EventEmitter } from 'events';
import { SessionStore } from './store.js';
import { SessionState } from './models.js';
import { formatEvent, FormattedEvent } from './event-formatter.js';

interface RunningSession {
  slug: string;
  pty: pty.IPty;
  claudeSessionId?: string;
  lastTextSummary?: string; // Track last text to deduplicate
}

export interface SessionManagerEvents {
  state_change: (slug: string, state: SessionState) => void;
  claude_event: (slug: string, event: unknown) => void;
  process_end: (slug: string, code: number | null) => void;
  output: (slug: string, data: string) => void;
  formatted_event: (slug: string, event: FormattedEvent) => void;
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
    // Use 'dumb' terminal to disable cursor/screen control codes
    const proc = pty.spawn(this.claudeCommand, args, {
      name: 'dumb',
      cols: 200,
      rows: 50,
      cwd: session.path,
      env: {
        ...process.env,
        NO_COLOR: '1',
        FORCE_COLOR: '0',
        TERM: 'dumb',
        CI: '1', // Some tools check this for non-interactive mode
      } as { [key: string]: string },
    });

    this.running.set(slug, { slug, pty: proc });
    this.store.update(slug, { state: 'working' });
    this.emit('state_change', slug, 'working');

    let buffer = '';

    proc.onData((data: string) => {
      // Emit raw output for debugging
      this.emit('output', slug, data);

      // Clean carriage returns and append to buffer
      buffer += data.replace(/\r/g, '');
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';

      const running = this.running.get(slug);

      for (const line of lines) {
        if (!line.trim()) continue;

        // Format and emit the event
        const formatted = formatEvent(line);
        if (formatted) {
          // Deduplicate text/thinking events with same summary
          if ((formatted.category === 'text' || formatted.category === 'thinking') && running) {
            if (formatted.summary === running.lastTextSummary) {
              continue; // Skip duplicate
            }
            running.lastTextSummary = formatted.summary;
          }

          console.log(`[${slug}] ${formatted.category}: ${formatted.summary}`);
          this.emit('formatted_event', slug, formatted);

          // Extract session ID from init events
          if (formatted.category === 'init' && formatted.sessionId) {
            const session = this.store.get(slug);
            if (session && !session.claudeSessionId) {
              this.store.update(slug, { claudeSessionId: formatted.sessionId });
            }
          }

          // Update state based on event type
          if (formatted.category === 'tool_use') {
            this.store.update(slug, { state: 'working' });
            this.emit('state_change', slug, 'working');
          } else if (formatted.category === 'thinking' || formatted.category === 'text') {
            this.store.update(slug, { state: 'thinking' });
            this.emit('state_change', slug, 'thinking');
          } else if (formatted.category === 'result') {
            // Result means Claude finished - check if waiting for input
            if (formatted.isActionable) {
              this.store.update(slug, { state: 'waiting' });
              this.emit('state_change', slug, 'waiting');
            }
          }
        }

        // Also try to parse as JSON for legacy handling
        try {
          const event = JSON.parse(line);
          this.handleClaudeEvent(slug, event);
        } catch {
          // Non-JSON output
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
