import React, { useState } from 'react';
import { Box, Text, useInput } from 'ink';
import TextInput from 'ink-text-input';

interface Props {
  slug: string;
  onSubmit: (text: string) => void;
  onCancel: () => void;
}

export function InputPrompt({ slug, onSubmit, onCancel }: Props) {
  const [value, setValue] = useState('');

  useInput((input, key) => {
    if (key.escape) {
      onCancel();
    }
  });

  const handleSubmit = (text: string) => {
    if (text.trim()) {
      onSubmit(text);
    }
  };

  return (
    <Box flexDirection="column" borderStyle="single" paddingX={1}>
      <Text bold color="cyan">
        Send input to {slug}:
      </Text>
      <Box marginTop={1}>
        <Text color="green">{'> '}</Text>
        <TextInput
          value={value}
          onChange={setValue}
          onSubmit={handleSubmit}
          placeholder="Type your response..."
        />
      </Box>
      <Box marginTop={1}>
        <Text dimColor>Enter to send | Esc to cancel</Text>
      </Box>
    </Box>
  );
}
