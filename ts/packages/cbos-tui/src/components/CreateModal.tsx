import React, { useState } from 'react';
import { Box, Text, useInput } from 'ink';
import TextInput from 'ink-text-input';

interface Props {
  onSubmit: (slug: string, path: string) => void;
  onCancel: () => void;
}

type Field = 'slug' | 'path';

export function CreateModal({ onSubmit, onCancel }: Props) {
  const [slug, setSlug] = useState('');
  const [path, setPath] = useState(process.cwd());
  const [activeField, setActiveField] = useState<Field>('slug');

  useInput((input, key) => {
    if (key.escape) {
      onCancel();
      return;
    }

    if (key.tab) {
      setActiveField((f) => (f === 'slug' ? 'path' : 'slug'));
    }
  });

  const handleSubmit = () => {
    if (slug.trim() && path.trim()) {
      onSubmit(slug.trim().toUpperCase(), path.trim());
    }
  };

  return (
    <Box flexDirection="column" borderStyle="double" paddingX={2} paddingY={1}>
      <Box marginBottom={1}>
        <Text bold color="cyan">Create New Session</Text>
      </Box>

      <Box marginBottom={1}>
        <Text color={activeField === 'slug' ? 'green' : 'white'}>Slug: </Text>
        {activeField === 'slug' ? (
          <TextInput
            value={slug}
            onChange={setSlug}
            onSubmit={() => setActiveField('path')}
            placeholder="SESSION_NAME"
          />
        ) : (
          <Text>{slug || '(empty)'}</Text>
        )}
      </Box>

      <Box marginBottom={1}>
        <Text color={activeField === 'path' ? 'green' : 'white'}>Path: </Text>
        {activeField === 'path' ? (
          <TextInput
            value={path}
            onChange={setPath}
            onSubmit={handleSubmit}
            placeholder="/path/to/project"
          />
        ) : (
          <Text>{path}</Text>
        )}
      </Box>

      <Box marginTop={1}>
        <Text dimColor>Tab to switch fields | Enter to confirm | Esc to cancel</Text>
      </Box>
    </Box>
  );
}
