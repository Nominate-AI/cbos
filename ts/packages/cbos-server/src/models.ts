import { z } from 'zod';

// Session States
export const SessionStateEnum = z.enum([
  'idle',
  'thinking',
  'working',
  'waiting',
  'error',
]);
export type SessionState = z.infer<typeof SessionStateEnum>;

// Session Schema
export const SessionSchema = z.object({
  slug: z.string(),
  path: z.string(),
  state: SessionStateEnum.default('idle'),
  claudeSessionId: z.string().optional(),
  createdAt: z.string().datetime(),
  lastActivity: z.string().datetime(),
  lastContext: z.string().optional(),
  messageCount: z.number().default(0),
});
export type Session = z.infer<typeof SessionSchema>;

// Event from Stop hook
export const WaitingEventSchema = z.object({
  event: z.literal('waiting_for_input'),
  id: z.string(),
  timestamp: z.string(),
  session: z.object({
    id: z.string(),
    transcript_path: z.string().optional(),
    message_count: z.number().optional(),
  }),
  context: z.object({
    preceding_text: z.string(),
    last_tool: z.string().nullable().optional(),
    text_preview: z.string(),
  }),
});
export type WaitingEvent = z.infer<typeof WaitingEventSchema>;

// WebSocket Messages - Server to Client
export type ServerMessage =
  | { type: 'sessions'; sessions: Session[] }
  | { type: 'session_update'; session: Session }
  | { type: 'session_waiting'; slug: string; context: string }
  | { type: 'session_created'; session: Session }
  | { type: 'session_deleted'; slug: string }
  | { type: 'claude_event'; slug: string; event: unknown }
  | { type: 'error'; message: string };

// WebSocket Messages - Client to Server
export type ClientMessage =
  | { type: 'subscribe'; sessions: string[] }
  | { type: 'create_session'; slug: string; path: string }
  | { type: 'delete_session'; slug: string }
  | { type: 'send_input'; slug: string; text: string }
  | { type: 'interrupt'; slug: string }
  | { type: 'list_sessions' };
