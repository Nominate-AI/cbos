import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';
import { Session, SessionSchema, SessionState } from './models.js';

export class SessionStore {
  private sessions: Map<string, Session> = new Map();
  private persistPath: string;

  constructor(persistPath?: string) {
    const cbosDir = join(homedir(), '.cbos');
    if (!existsSync(cbosDir)) {
      mkdirSync(cbosDir, { recursive: true });
    }
    this.persistPath = persistPath ?? join(cbosDir, 'ts-sessions.json');
    this.load();
  }

  private load(): void {
    if (!existsSync(this.persistPath)) return;
    try {
      const raw = readFileSync(this.persistPath, 'utf-8');
      const data = JSON.parse(raw);
      for (const [slug, session] of Object.entries(data.sessions || {})) {
        const parsed = SessionSchema.safeParse(session);
        if (parsed.success) {
          this.sessions.set(slug, parsed.data);
        }
      }
      console.log(`Loaded ${this.sessions.size} sessions from ${this.persistPath}`);
    } catch (e) {
      console.error('Failed to load sessions:', e);
    }
  }

  private save(): void {
    const data = {
      sessions: Object.fromEntries(this.sessions),
      savedAt: new Date().toISOString(),
    };
    writeFileSync(this.persistPath, JSON.stringify(data, null, 2));
  }

  create(slug: string, path: string): Session {
    if (this.sessions.has(slug)) {
      throw new Error(`Session "${slug}" already exists`);
    }
    const now = new Date().toISOString();
    const session: Session = {
      slug,
      path,
      state: 'idle',
      createdAt: now,
      lastActivity: now,
      messageCount: 0,
    };
    this.sessions.set(slug, session);
    this.save();
    return session;
  }

  get(slug: string): Session | undefined {
    return this.sessions.get(slug);
  }

  all(): Session[] {
    return Array.from(this.sessions.values());
  }

  update(slug: string, updates: Partial<Omit<Session, 'slug'>>): Session | undefined {
    const session = this.sessions.get(slug);
    if (!session) return undefined;

    Object.assign(session, updates, {
      lastActivity: new Date().toISOString(),
    });
    this.save();
    return session;
  }

  setState(slug: string, state: SessionState): Session | undefined {
    return this.update(slug, { state });
  }

  delete(slug: string): boolean {
    const deleted = this.sessions.delete(slug);
    if (deleted) {
      this.save();
    }
    return deleted;
  }

  findByClaudeSessionId(claudeSessionId: string): Session | undefined {
    for (const session of this.sessions.values()) {
      if (session.claudeSessionId === claudeSessionId) {
        return session;
      }
    }
    return undefined;
  }
}
