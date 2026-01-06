import React from 'react';
import { Box, Text } from 'ink';

interface Props {
  left: string;
  right: string;
  connected: boolean;
}

export function StatusBar({ left, right, connected }: Props) {
  return (
    <Box
      borderStyle="single"
      borderTop
      borderBottom={false}
      borderLeft={false}
      borderRight={false}
      paddingX={1}
      justifyContent="space-between"
    >
      <Text dimColor>{left}</Text>
      <Box>
        <Text color={connected ? 'green' : 'red'}>
          {connected ? '●' : '○'}
        </Text>
        <Text dimColor> {right}</Text>
      </Box>
    </Box>
  );
}
