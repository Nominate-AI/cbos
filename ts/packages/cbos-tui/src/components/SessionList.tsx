import React, { useState, useEffect } from 'react';
import { Box, Text, useInput } from 'ink';
import type { Session, SessionState } from '../hooks/useServer.js';

const STATE_DISPLAY: Record<SessionState, { icon: string; color: string }> = {
  waiting: { icon: '●', color: 'red' },
  thinking: { icon: '◐', color: 'yellow' },
  working: { icon: '◑', color: 'cyan' },
  idle: { icon: '○', color: 'gray' },
  error: { icon: '✗', color: 'red' },
};

interface Props {
  sessions: Session[];
  selectedIndex: number;
  onSelect: (index: number) => void;
  onEnter: (session: Session) => void;
  active: boolean;
}

export function SessionList({ sessions, selectedIndex, onSelect, onEnter, active }: Props) {
  useInput(
    (input, key) => {
      if (!active) return;

      if (input === 'j' || key.downArrow) {
        onSelect(Math.min(selectedIndex + 1, sessions.length - 1));
      }
      if (input === 'k' || key.upArrow) {
        onSelect(Math.max(selectedIndex - 1, 0));
      }
      if (key.return) {
        const session = sessions[selectedIndex];
        if (session) {
          onEnter(session);
        }
      }
    },
    { isActive: active }
  );

  if (sessions.length === 0) {
    return (
      <Box flexDirection="column" padding={1}>
        <Text dimColor>No sessions.</Text>
        <Text dimColor>Press 'n' to create a new session.</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" paddingX={1}>
      <Box marginBottom={1}>
        <Text bold underline>Sessions</Text>
      </Box>
      {sessions.map((session, index) => {
        const { icon, color } = STATE_DISPLAY[session.state] ?? STATE_DISPLAY.idle;
        const isSelected = index === selectedIndex;
        const isWaiting = session.state === 'waiting';

        return (
          <Box key={session.slug}>
            <Text color={isSelected ? 'cyan' : undefined} bold={isSelected}>
              {isSelected ? '❯ ' : '  '}
            </Text>
            <Text color={color}>{icon} </Text>
            <Text bold={isWaiting} color={isWaiting ? 'red' : undefined}>
              {session.slug}
            </Text>
            <Text dimColor> {session.path.replace(process.env.HOME ?? '', '~')}</Text>
            {session.messageCount > 0 && (
              <Text dimColor> [{session.messageCount}]</Text>
            )}
          </Box>
        );
      })}
    </Box>
  );
}
