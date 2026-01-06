import { existsSync, readFileSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';
import { z } from 'zod';

const ConfigSchema = z.object({
  port: z.number().default(32205),
  claudeCommand: z.string().default('claude'),
  persistPath: z.string().optional(),
  hookEnabled: z.boolean().default(true),
  eventsDir: z.string().optional(),
});

export type Config = z.infer<typeof ConfigSchema>;

export function loadConfig(): Config {
  // Environment variables take precedence
  const envConfig: Partial<Config> = {};

  if (process.env.CBOS_PORT) {
    envConfig.port = parseInt(process.env.CBOS_PORT, 10);
  }
  if (process.env.CBOS_CLAUDE_COMMAND) {
    envConfig.claudeCommand = process.env.CBOS_CLAUDE_COMMAND;
  }
  if (process.env.CBOS_EVENTS_DIR) {
    envConfig.eventsDir = process.env.CBOS_EVENTS_DIR;
  }

  // Try to load from config file
  const configPath = join(homedir(), '.cbos', 'ts-config.json');
  let fileConfig: Partial<Config> = {};

  if (existsSync(configPath)) {
    try {
      const raw = readFileSync(configPath, 'utf-8');
      fileConfig = JSON.parse(raw);
    } catch (e) {
      console.warn('Failed to load config file:', e);
    }
  }

  // Merge: defaults < file < env
  const merged = { ...fileConfig, ...envConfig };
  return ConfigSchema.parse(merged);
}

// Default paths
export function getEventsDir(config: Config): string {
  return config.eventsDir ?? join(homedir(), '.claude', 'cbos');
}

export function getEventsLogPath(config: Config): string {
  return join(getEventsDir(config), 'events.jsonl');
}
