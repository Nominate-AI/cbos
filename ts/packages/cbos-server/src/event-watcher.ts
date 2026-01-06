import { watch } from 'chokidar';
import { createReadStream, statSync, existsSync, mkdirSync, writeFileSync } from 'fs';
import { createInterface } from 'readline';
import { dirname } from 'path';
import { WaitingEvent, WaitingEventSchema } from './models.js';

export type EventCallback = (event: WaitingEvent) => void;

export class EventWatcher {
  private eventLogPath: string;
  private lastPosition = 0;
  private callbacks: EventCallback[] = [];
  private watcher: ReturnType<typeof watch> | null = null;
  private isProcessing = false;

  constructor(eventLogPath: string) {
    this.eventLogPath = eventLogPath;
  }

  onEvent(callback: EventCallback): void {
    this.callbacks.push(callback);
  }

  start(): void {
    // Ensure directory exists
    const dir = dirname(this.eventLogPath);
    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true });
    }

    // Create file if doesn't exist
    if (!existsSync(this.eventLogPath)) {
      writeFileSync(this.eventLogPath, '');
    }

    // Get initial file size to skip existing content
    this.lastPosition = statSync(this.eventLogPath).size;

    this.watcher = watch(this.eventLogPath, {
      persistent: true,
      awaitWriteFinish: {
        stabilityThreshold: 50,
        pollInterval: 10,
      },
    });

    this.watcher.on('change', () => this.processNewLines());
    this.watcher.on('add', () => {
      // File was recreated, reset position
      this.lastPosition = 0;
      this.processNewLines();
    });

    console.log(`Watching for events: ${this.eventLogPath}`);
  }

  stop(): void {
    if (this.watcher) {
      this.watcher.close();
      this.watcher = null;
    }
  }

  private async processNewLines(): Promise<void> {
    if (this.isProcessing || !existsSync(this.eventLogPath)) return;

    this.isProcessing = true;

    try {
      const stats = statSync(this.eventLogPath);
      if (stats.size <= this.lastPosition) {
        // File was truncated or no new content
        if (stats.size < this.lastPosition) {
          this.lastPosition = 0;
        }
        return;
      }

      const stream = createReadStream(this.eventLogPath, {
        start: this.lastPosition,
        encoding: 'utf-8',
      });

      const rl = createInterface({
        input: stream,
        crlfDelay: Infinity,
      });

      let newPosition = this.lastPosition;

      for await (const line of rl) {
        newPosition += Buffer.byteLength(line, 'utf-8') + 1; // +1 for newline

        if (!line.trim()) continue;

        try {
          const parsed = JSON.parse(line);
          const result = WaitingEventSchema.safeParse(parsed);

          if (result.success) {
            console.log(`Event received: session=${result.data.session.id}`);
            for (const callback of this.callbacks) {
              try {
                callback(result.data);
              } catch (e) {
                console.error('Event callback error:', e);
              }
            }
          }
        } catch {
          // Skip malformed JSON lines
        }
      }

      this.lastPosition = newPosition;
    } finally {
      this.isProcessing = false;
    }
  }
}
