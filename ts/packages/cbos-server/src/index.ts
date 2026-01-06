#!/usr/bin/env node

import { CBOSServer } from './server.js';
import { EventWatcher } from './event-watcher.js';
import { SessionManager } from './session-manager.js';
import { installHook } from './hook-installer.js';
import { loadConfig, getEventsLogPath } from './config.js';

async function main() {
  console.log('Starting CBOS Server...');

  // Load configuration
  const config = loadConfig();
  console.log(`Configuration: port=${config.port}, claude=${config.claudeCommand}`);

  // Install hook if enabled
  if (config.hookEnabled) {
    const hookResult = installHook();
    console.log(`Hook: ${hookResult.message}`);
  }

  // Create server
  const server = new CBOSServer(config.port);

  // Create session manager
  const sessionManager = new SessionManager(server.getStore(), config.claudeCommand);

  // Forward session manager events to WebSocket clients
  sessionManager.on('claude_event', (slug: string, event: unknown) => {
    server.broadcastClaudeEvent(slug, event);
  });

  sessionManager.on('state_change', (slug: string, state: string) => {
    const session = server.getStore().get(slug);
    if (session) {
      server.broadcast({ type: 'session_update', session }, slug);
    }
  });

  // Forward raw output to WebSocket clients
  sessionManager.on('output', (slug: string, data: string) => {
    console.log(`Broadcasting output to ${slug}: ${data.length} bytes`);
    server.broadcast({ type: 'output', slug, data }, slug);
  });

  // Handle send_input from WebSocket clients
  server.on('send_input', async (slug: string, text: string) => {
    console.log(`>>> Received send_input for ${slug}: "${text.slice(0, 50)}..."`);
    try {
      await sessionManager.invoke(slug, text);
      console.log(`>>> invoke() completed for ${slug}`);
    } catch (e) {
      console.error(`Failed to invoke session ${slug}:`, e);
    }
  });

  // Handle interrupt from WebSocket clients
  server.on('interrupt', (slug: string) => {
    sessionManager.interrupt(slug);
  });

  // Create event watcher for Stop hook
  const eventsLogPath = getEventsLogPath(config);
  const watcher = new EventWatcher(eventsLogPath);

  watcher.onEvent((event) => {
    console.log(`Waiting event: session=${event.session.id}`);

    // Try to find the session by Claude session ID
    let session = server.getStore().findByClaudeSessionId(event.session.id);

    // If not found, try slug match (session ID might be the slug)
    if (!session) {
      session = server.getStore().get(event.session.id);
    }

    if (session) {
      server.onSessionWaiting(session.slug, event.context.preceding_text);
    } else {
      console.log(`No matching session found for Claude session: ${event.session.id}`);
    }
  });

  watcher.start();

  // Handle graceful shutdown
  const shutdown = () => {
    console.log('\nShutting down...');
    watcher.stop();
    server.close();
    process.exit(0);
  };

  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);

  console.log(`\nCBOS Server ready!`);
  console.log(`  WebSocket: ws://localhost:${config.port}`);
  console.log(`  Events: ${eventsLogPath}`);
  console.log(`\nPress Ctrl+C to stop.`);
}

main().catch((err) => {
  console.error('Fatal error:', err);
  process.exit(1);
});
