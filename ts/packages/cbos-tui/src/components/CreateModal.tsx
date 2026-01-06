import React, { useState, useEffect } from 'react';
import { Box, Text, useInput } from 'ink';
import SelectInput from 'ink-select-input';
import { discoverClaudeProjects, Project } from '../utils/projectDiscovery.js';

interface Props {
  activePaths: Set<string>;
  onSubmit: (slug: string, path: string) => void;
  onCancel: () => void;
}

const PAGE_SIZE = 8;

export function CreateModal({ activePaths, onSubmit, onCancel }: Props) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);

  useEffect(() => {
    // Discover projects asynchronously
    const discovered = discoverClaudeProjects(activePaths);
    setProjects(discovered);
    setLoading(false);
  }, [activePaths]);

  useInput((input, key) => {
    if (key.escape) {
      onCancel();
      return;
    }

    // Pagination
    if (input === 'n' || key.rightArrow) {
      const maxPage = Math.ceil(projects.length / PAGE_SIZE) - 1;
      if (page < maxPage) {
        setPage(page + 1);
      }
    }

    if (input === 'p' || key.leftArrow) {
      if (page > 0) {
        setPage(page - 1);
      }
    }
  });

  const handleSelect = (item: { value: Project }) => {
    onSubmit(item.value.name, item.value.path);
  };

  if (loading) {
    return (
      <Box flexDirection="column" borderStyle="double" paddingX={2} paddingY={1}>
        <Text bold color="cyan">Discovering Claude projects...</Text>
        <Text dimColor>Scanning for CLAUDE.md files in home directory</Text>
      </Box>
    );
  }

  if (projects.length === 0) {
    return (
      <Box flexDirection="column" borderStyle="double" paddingX={2} paddingY={1}>
        <Text bold color="yellow">No Claude projects found</Text>
        <Text dimColor>Looking for directories with CLAUDE.md files</Text>
        <Box marginTop={1}>
          <Text dimColor>Esc to close</Text>
        </Box>
      </Box>
    );
  }

  const totalPages = Math.ceil(projects.length / PAGE_SIZE);
  const startIdx = page * PAGE_SIZE;
  const pageProjects = projects.slice(startIdx, startIdx + PAGE_SIZE);

  // Shorten path for display (remove home prefix)
  const home = process.env.HOME ?? '';
  const items = pageProjects.map((p) => ({
    key: p.path,  // Unique key for React
    label: `${p.name}  ${p.path.replace(home, '~')}`,
    value: p,
  }));

  return (
    <Box flexDirection="column" borderStyle="double" paddingX={2} paddingY={1}>
      <Box marginBottom={1}>
        <Text bold color="cyan">Create New Session</Text>
        <Text dimColor> - Select a project</Text>
      </Box>

      <SelectInput items={items} onSelect={handleSelect} />

      {/* Pagination */}
      {totalPages > 1 && (
        <Box marginTop={1}>
          <Text dimColor>
            Page {page + 1}/{totalPages} ({projects.length} projects) | n/→ next | p/← prev
          </Text>
        </Box>
      )}

      <Box marginTop={1}>
        <Text dimColor>Enter to select | Esc to cancel</Text>
      </Box>
    </Box>
  );
}
