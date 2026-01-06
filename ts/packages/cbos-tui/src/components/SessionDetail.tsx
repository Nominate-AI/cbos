import React from 'react';
import { Box, Text } from 'ink';
import type { Session } from '../hooks/useServer.js';

interface Props {
  session: Session;
}

export function SessionDetail({ session }: Props) {
  const stateColors: Record<string, string> = {
    waiting: 'red',
    thinking: 'yellow',
    working: 'cyan',
    idle: 'gray',
    error: 'red',
  };

  return (
    <Box flexDirection="column" paddingX={1} flexGrow={1}>
      <Box marginBottom={1}>
        <Text bold>{session.slug}</Text>
        <Text> - </Text>
        <Text color={stateColors[session.state] ?? 'white'}>{session.state.toUpperCase()}</Text>
      </Box>

      <Box marginBottom={1}>
        <Text dimColor>Path: </Text>
        <Text>{session.path}</Text>
      </Box>

      <Box marginBottom={1}>
        <Text dimColor>Messages: </Text>
        <Text>{session.messageCount}</Text>
      </Box>

      {session.claudeSessionId && (
        <Box marginBottom={1}>
          <Text dimColor>Claude ID: </Text>
          <Text>{session.claudeSessionId}</Text>
        </Box>
      )}

      <Box marginBottom={1}>
        <Text dimColor>Last Activity: </Text>
        <Text>{new Date(session.lastActivity).toLocaleString()}</Text>
      </Box>

      {session.lastContext && (
        <Box flexDirection="column" marginTop={1}>
          <Text bold underline>Last Response</Text>
          <Box marginTop={1} borderStyle="single" paddingX={1} paddingY={0}>
            <Text wrap="wrap">
              {session.lastContext.length > 500
                ? session.lastContext.slice(0, 500) + '...'
                : session.lastContext}
            </Text>
          </Box>
        </Box>
      )}
    </Box>
  );
}
