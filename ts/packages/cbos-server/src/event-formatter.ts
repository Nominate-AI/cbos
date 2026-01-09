/**
 * Claude Event Formatter
 * Parses stream-json events and formats them for display
 */

// Event categories for UI styling and automation
export type EventCategory =
  | 'init'           // Session started
  | 'thinking'       // Claude is processing
  | 'text'           // Text output from Claude
  | 'tool_use'       // Claude is calling a tool
  | 'tool_result'    // Tool returned a result
  | 'result'         // Final result with stats
  | 'error'          // Error occurred
  | 'waiting'        // Waiting for user input
  | 'question'       // AskUserQuestion - needs user response
  | 'system'         // System status/info messages
  | 'compact'        // Context compaction boundary
  | 'user_msg'       // User message in conversation
  | 'unknown';       // Unrecognized event

export interface FormattedEvent {
  category: EventCategory;
  timestamp: string;
  summary: string;        // Short one-line summary
  details?: string;       // Extended details (optional)
  raw?: unknown;          // Original event data

  // For automation
  isActionable: boolean;  // Can AI respond to this?
  priority: 'low' | 'normal' | 'high' | 'critical';

  // Specific fields by category
  toolName?: string;      // For tool_use/tool_result
  toolInput?: string;     // Tool input preview
  toolOutput?: string;    // Tool output preview
  cost?: number;          // API cost in USD
  duration?: number;      // Duration in ms
  sessionId?: string;     // Claude session ID

  // For question events (AskUserQuestion)
  questionOptions?: string[];  // List of options for the question
}

// ANSI escape code stripper - comprehensive pattern
const ANSI_PATTERN = /\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[()][AB012]|\x1b[\[\]PX^_][^\x1b]*|\x1b./g;

// Box drawing and other terminal UI characters that leak through
const BOX_DRAWING_PATTERN = /[│┌┐└┘├┤┬┴┼─═║╔╗╚╝╠╣╦╩╬▶▷◀◁●○◐◑◒◓]/g;

function stripAnsi(text: string): string {
  return text
    .replace(ANSI_PATTERN, '')           // Remove ANSI escape sequences
    .replace(/\r/g, '')                   // Remove carriage returns
    .replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g, '') // Remove other control chars
    .replace(/^\s*[│┃]\s*/gm, '')         // Remove box drawing line prefixes
    .replace(/^[│┃]/gm, '');              // Remove standalone vertical bars at line start
}

function truncate(text: string, maxLen: number): string {
  const clean = stripAnsi(text).trim();
  if (clean.length <= maxLen) return clean;
  return clean.slice(0, maxLen - 3) + '...';
}

function extractTextContent(message: unknown): string {
  if (!message || typeof message !== 'object') return '';

  const msg = message as Record<string, unknown>;
  const content = msg.content;

  if (typeof content === 'string') return content;

  if (Array.isArray(content)) {
    const texts: string[] = [];
    for (const block of content) {
      if (typeof block === 'object' && block !== null) {
        const b = block as Record<string, unknown>;
        if (b.type === 'text' && typeof b.text === 'string') {
          texts.push(b.text);
        }
      }
    }
    return texts.join('\n');
  }

  return '';
}

function extractToolUse(message: unknown): { name: string; input: string } | null {
  if (!message || typeof message !== 'object') return null;

  const msg = message as Record<string, unknown>;
  const content = msg.content;

  if (Array.isArray(content)) {
    for (const block of content) {
      if (typeof block === 'object' && block !== null) {
        const b = block as Record<string, unknown>;
        if (b.type === 'tool_use') {
          const name = typeof b.name === 'string' ? b.name : 'unknown';
          const input = b.input ? JSON.stringify(b.input) : '';
          return { name, input: truncate(input, 100) };
        }
      }
    }
  }

  return null;
}

function extractAskUserQuestion(message: unknown): { question: string; options: string[] } | null {
  if (!message || typeof message !== 'object') return null;

  const msg = message as Record<string, unknown>;
  const content = msg.content;

  if (Array.isArray(content)) {
    for (const block of content) {
      if (typeof block === 'object' && block !== null) {
        const b = block as Record<string, unknown>;
        if (b.type === 'tool_use' && b.name === 'AskUserQuestion') {
          const input = b.input as Record<string, unknown> | undefined;
          if (input && Array.isArray(input.questions)) {
            const questions = input.questions as Array<Record<string, unknown>>;
            const allOptions: string[] = [];
            let questionText = '';

            for (const q of questions) {
              if (q.question) {
                questionText = questionText ? `${questionText} | ${q.question}` : String(q.question);
              }
              if (Array.isArray(q.options)) {
                for (const opt of q.options as Array<Record<string, unknown>>) {
                  if (opt.label) {
                    allOptions.push(String(opt.label));
                  }
                }
              }
            }

            return { question: questionText, options: allOptions };
          }
        }
      }
    }
  }

  return null;
}

function extractToolResult(message: unknown): { output: string } | null {
  if (!message || typeof message !== 'object') return null;

  const msg = message as Record<string, unknown>;
  const content = msg.content;

  if (Array.isArray(content)) {
    for (const block of content) {
      if (typeof block === 'object' && block !== null) {
        const b = block as Record<string, unknown>;
        if (b.type === 'tool_result') {
          const output = typeof b.content === 'string' ? b.content : JSON.stringify(b.content);
          return { output: truncate(output, 200) };
        }
      }
    }
  }

  return null;
}

export function formatEvent(jsonLine: string): FormattedEvent | null {
  const timestamp = new Date().toISOString();

  let event: Record<string, unknown>;
  try {
    event = JSON.parse(jsonLine);
  } catch {
    // Not JSON - might be plain text or ANSI
    const clean = stripAnsi(jsonLine).trim();
    if (!clean) return null;

    return {
      category: 'text',
      timestamp,
      summary: truncate(clean, 80),
      details: clean,
      isActionable: false,
      priority: 'low',
    };
  }

  const type = event.type as string;
  const subtype = event.subtype as string | undefined;

  switch (type) {
    case 'system': {
      if (subtype === 'init') {
        const sessionId = event.session_id as string | undefined;
        const cwd = event.cwd as string | undefined;
        return {
          category: 'init',
          timestamp,
          summary: `Session started: ${sessionId?.slice(0, 8) || 'unknown'}...`,
          details: cwd ? `Working directory: ${cwd}` : undefined,
          sessionId,
          isActionable: false,
          priority: 'low',
          raw: event,
        };
      }

      if (subtype === 'status') {
        const status = event.status as string | null;
        if (status === null) {
          return null; // Skip null status updates
        }
        return {
          category: 'system',
          timestamp,
          summary: `Status: ${status}`,
          isActionable: false,
          priority: 'low',
          raw: event,
        };
      }

      if (subtype === 'compact_boundary') {
        return {
          category: 'compact',
          timestamp,
          summary: '── Context compacted ──',
          isActionable: false,
          priority: 'low',
          raw: event,
        };
      }

      // Generic system message
      return {
        category: 'system',
        timestamp,
        summary: `System: ${subtype || 'info'}`,
        isActionable: false,
        priority: 'low',
        raw: event,
      };
    }

    case 'assistant': {
      const message = event.message;

      // Check for AskUserQuestion first (special tool)
      const askQuestion = extractAskUserQuestion(message);
      if (askQuestion) {
        const optionsPreview = askQuestion.options.length > 0
          ? ` [${askQuestion.options.join(' | ')}]`
          : '';
        return {
          category: 'question',
          timestamp,
          summary: truncate(askQuestion.question, 60) + optionsPreview,
          details: askQuestion.question,
          questionOptions: askQuestion.options,
          isActionable: true,
          priority: 'high',
          raw: event,
        };
      }

      // Check for other tool uses
      const toolUse = extractToolUse(message);
      if (toolUse) {
        return {
          category: 'tool_use',
          timestamp,
          summary: `${toolUse.name}`,
          details: toolUse.input,
          toolName: toolUse.name,
          toolInput: toolUse.input,
          isActionable: false,
          priority: 'normal',
          raw: event,
        };
      }

      const text = extractTextContent(message);
      if (text) {
        return {
          category: 'text',
          timestamp,
          summary: truncate(text, 80),
          details: text,
          isActionable: false,
          priority: 'normal',
          raw: event,
        };
      }

      // Thinking/processing
      return {
        category: 'thinking',
        timestamp,
        summary: '◐ Thinking...',
        isActionable: false,
        priority: 'low',
        raw: event,
      };
    }

    case 'user': {
      const message = event.message;
      const toolResult = extractToolResult(message);

      if (toolResult) {
        return {
          category: 'tool_result',
          timestamp,
          summary: `Tool completed`,
          details: toolResult.output,
          toolOutput: toolResult.output,
          isActionable: false,
          priority: 'low',
          raw: event,
        };
      }

      // Regular user message
      const userText = extractTextContent(message);
      if (userText) {
        return {
          category: 'user_msg',
          timestamp,
          summary: truncate(userText, 80),
          details: userText,
          isActionable: false,
          priority: 'low',
          raw: event,
        };
      }
      break;
    }

    case 'result': {
      const isError = event.is_error as boolean;
      const duration = event.duration_ms as number | undefined;
      const cost = event.cost_usd as number | undefined;
      const resultSubtype = event.subtype as string;

      if (isError) {
        return {
          category: 'error',
          timestamp,
          summary: `✗ Error: ${resultSubtype}`,
          isActionable: true,
          priority: 'critical',
          duration,
          cost,
          raw: event,
        };
      }

      // Check if waiting for input (end of turn)
      if (resultSubtype === 'end_turn' || resultSubtype === 'success') {
        return {
          category: 'result',
          timestamp,
          summary: `✓ Complete (${((duration || 0) / 1000).toFixed(1)}s, $${(cost || 0).toFixed(4)})`,
          isActionable: true, // Might need follow-up
          priority: 'normal',
          duration,
          cost,
          raw: event,
        };
      }
      break;
    }

    case 'error': {
      const message = event.message as string || 'Unknown error';
      return {
        category: 'error',
        timestamp,
        summary: `✗ ${truncate(message, 60)}`,
        details: message,
        isActionable: true,
        priority: 'critical',
        raw: event,
      };
    }
  }

  // Unknown event type
  return {
    category: 'unknown',
    timestamp,
    summary: `[${type || 'unknown'}] ${truncate(JSON.stringify(event), 50)}`,
    isActionable: false,
    priority: 'low',
    raw: event,
  };
}

/**
 * Parse a buffer of output into formatted events
 */
export function parseOutputBuffer(buffer: string): { events: FormattedEvent[]; remainder: string } {
  const events: FormattedEvent[] = [];
  // Split by newline, handle both \n and \r\n
  const lines = buffer.replace(/\r/g, '').split('\n');
  const remainder = lines.pop() ?? ''; // Keep incomplete line

  for (const line of lines) {
    const trimmed = stripAnsi(line).trim();
    if (!trimmed) continue;

    const formatted = formatEvent(trimmed);
    if (formatted) {
      events.push(formatted);
    }
  }

  return { events, remainder };
}
