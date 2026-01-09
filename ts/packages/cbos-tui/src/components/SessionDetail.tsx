import React, { useMemo } from 'react';
import { Box, Text, useStdout } from 'ink';
import type { Session, FormattedEvent, EventCategory } from '../hooks/useServer.js';

interface Props {
  session: Session;
}

// Icon and color mapping for event categories
const categoryConfig: Record<EventCategory, { icon: string; color: string; label: string }> = {
  init: { icon: '▶', color: 'gray', label: 'Init' },
  thinking: { icon: '◐', color: 'yellow', label: 'Think' },
  text: { icon: '💬', color: 'white', label: 'Text' },
  tool_use: { icon: '⚙', color: 'cyan', label: 'Tool' },
  tool_result: { icon: '✓', color: 'green', label: 'TRes' },
  result: { icon: '●', color: 'blue', label: 'Done' },
  error: { icon: '✗', color: 'red', label: 'Err' },
  waiting: { icon: '⏳', color: 'magenta', label: 'Wait' },
  question: { icon: '❓', color: 'yellow', label: 'Ask' },
  system: { icon: '⚡', color: 'gray', label: 'Sys' },
  compact: { icon: '📦', color: 'magenta', label: 'Compact' },
  user_msg: { icon: '👤', color: 'green', label: 'User' },
  unknown: { icon: '·', color: 'gray', label: '???' },
};

// Memoized event line component - only re-renders if event changes
const EventLine = React.memo(function EventLine({ event, maxWidth }: { event: FormattedEvent; maxWidth: number }) {
  const config = categoryConfig[event.category];

  // Use available width minus icon (2 chars) and padding (4 chars for border + padding)
  const textWidth = Math.max(40, maxWidth - 6);
  const summary = event.summary.length > textWidth
    ? event.summary.slice(0, textWidth - 3) + '...'
    : event.summary;

  return (
    <Text>
      <Text color={config.color}>{config.icon}</Text>
      <Text> </Text>
      <Text color={config.color}>{summary}</Text>
    </Text>
  );
}, (prev, next) =>
  prev.event.timestamp === next.event.timestamp &&
  prev.event.summary === next.event.summary &&
  prev.maxWidth === next.maxWidth
);

// Legend component showing all event types
function Legend() {
  const items: EventCategory[] = [
    'init', 'thinking', 'text', 'tool_use', 'tool_result',
    'result', 'question', 'system', 'compact', 'user_msg', 'error'
  ];

  return (
    <Box flexDirection="row" flexWrap="wrap">
      {items.map((cat) => {
        const config = categoryConfig[cat];
        return (
          <Box key={cat} marginRight={1}>
            <Text color={config.color}>{config.icon}</Text>
            <Text dimColor>{config.label} </Text>
          </Box>
        );
      })}
    </Box>
  );
}

export const SessionDetail = React.memo(function SessionDetail({ session }: Props) {
  const { stdout } = useStdout();

  // Get terminal dimensions
  const terminalWidth = stdout?.columns ?? 120;
  const terminalHeight = stdout?.rows ?? 24;

  // Calculate available height for events (reserve lines for header, footer, borders, legend)
  const reservedLines = 12; // header, path, activity header, borders, status bar, waiting indicator, legend
  const maxVisibleEvents = Math.max(5, terminalHeight - reservedLines);

  const stateColors: Record<string, string> = {
    waiting: 'red',
    thinking: 'yellow',
    working: 'cyan',
    idle: 'gray',
    error: 'red',
  };

  const events = session.events || [];

  // Memoize the visible events slice
  const visibleEvents = useMemo(() => {
    return events.slice(-maxVisibleEvents);
  }, [events, maxVisibleEvents]);

  // Memoize stats calculation
  const stats = useMemo(() => {
    const resultEvent = events.find((e) => e.category === 'result');
    const toolUseCount = events.filter((e) => e.category === 'tool_use').length;
    return { resultEvent, toolUseCount };
  }, [events]);

  return (
    <Box flexDirection="column" paddingX={1}>
      {/* Header - fixed */}
      <Box>
        <Text bold>{session.slug}</Text>
        <Text> - </Text>
        <Text color={stateColors[session.state] ?? 'white'}>{session.state.toUpperCase()}</Text>
        {stats.resultEvent && (
          <Text dimColor>
            {' '}| {stats.toolUseCount} tools | ${stats.resultEvent.cost?.toFixed(4) || '0.00'}
          </Text>
        )}
      </Box>

      {/* Path - fixed */}
      <Box>
        <Text dimColor>Path: {session.path}</Text>
      </Box>

      {/* Activity header */}
      <Box marginTop={1}>
        <Text bold>Activity ({events.length} events, showing last {visibleEvents.length})</Text>
      </Box>

      {/* Events - fixed height viewport */}
      <Box
        flexDirection="column"
        height={maxVisibleEvents}
        borderStyle="single"
        paddingX={1}
        overflowY="hidden"
      >
        {visibleEvents.length > 0 ? (
          visibleEvents.map((event, i) => (
            <EventLine key={`${event.timestamp}-${i}`} event={event} maxWidth={terminalWidth} />
          ))
        ) : (
          <Text dimColor>No activity yet. Press 'i' to send a message.</Text>
        )}
      </Box>

      {/* Waiting indicator - fixed at bottom */}
      {session.state === 'waiting' && (
        <Box marginTop={1}>
          <Text color="yellow" bold>⚡ Waiting for input - Press 'i' to respond</Text>
        </Box>
      )}

      {/* Legend */}
      <Box marginTop={1}>
        <Legend />
      </Box>
    </Box>
  );
}, (prev, next) => {
  // Custom comparison - only re-render if relevant props changed
  return (
    prev.session.slug === next.session.slug &&
    prev.session.state === next.session.state &&
    prev.session.events?.length === next.session.events?.length &&
    prev.session.events?.at(-1)?.timestamp === next.session.events?.at(-1)?.timestamp
  );
});
