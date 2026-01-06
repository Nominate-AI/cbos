import React, { useState } from 'react';
import { Box, Text, useInput, useApp } from 'ink';
import { useServer, Session } from './hooks/useServer.js';
import { SessionList } from './components/SessionList.js';
import { SessionDetail } from './components/SessionDetail.js';
import { StatusBar } from './components/StatusBar.js';
import { InputPrompt } from './components/InputPrompt.js';
import { CreateModal } from './components/CreateModal.js';

type View = 'list' | 'detail';
type Modal = 'none' | 'input' | 'create';

export function App() {
  const { exit } = useApp();
  const { connected, sessions, error, createSession, deleteSession, sendInput, interrupt } =
    useServer();

  const [view, setView] = useState<View>('list');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [modal, setModal] = useState<Modal>('none');

  const selectedSession = sessions[selectedIndex];
  const waitingCount = sessions.filter((s) => s.state === 'waiting').length;
  const workingCount = sessions.filter((s) => s.state === 'working' || s.state === 'thinking').length;

  // Global keybindings (when no modal is active)
  useInput(
    (input, key) => {
      // Quit
      if (input === 'q') {
        exit();
        return;
      }

      // View switching
      if (input === 'l') {
        setView('list');
        return;
      }

      if (input === 'd' && selectedSession) {
        setView('detail');
        return;
      }

      // Actions
      // Allow input for both 'idle' (first prompt) and 'waiting' (responding to question)
      if (input === 'i' && selectedSession && (selectedSession.state === 'waiting' || selectedSession.state === 'idle')) {
        setModal('input');
        return;
      }

      if (input === 'n') {
        setModal('create');
        return;
      }

      if (input === 'c' && selectedSession) {
        interrupt(selectedSession.slug);
        return;
      }

      if (input === 'x' && selectedSession) {
        deleteSession(selectedSession.slug);
        if (selectedIndex > 0) {
          setSelectedIndex(selectedIndex - 1);
        }
        return;
      }

      if (key.escape) {
        setView('list');
        return;
      }
    },
    { isActive: modal === 'none' }
  );

  const handleSessionSelect = (index: number) => {
    setSelectedIndex(index);
  };

  const handleSessionEnter = (session: Session) => {
    setView('detail');
    // Auto-open input for idle (first prompt) or waiting (question) sessions
    if (session.state === 'waiting' || session.state === 'idle') {
      setModal('input');
    }
  };

  const handleInputSubmit = (text: string) => {
    if (selectedSession) {
      sendInput(selectedSession.slug, text);
    }
    setModal('none');
  };

  const handleCreateSubmit = (slug: string, path: string) => {
    createSession(slug, path);
    setModal('none');
  };

  return (
    <Box flexDirection="column" height="100%">
      {/* Header */}
      <Box
        borderStyle="single"
        borderBottom
        borderTop={false}
        borderLeft={false}
        borderRight={false}
        paddingX={1}
      >
        <Text bold color="cyan">
          CBOS
        </Text>
        <Text dimColor> - Claude Code Session Manager</Text>
        {error && (
          <Text color="red"> | Error: {error}</Text>
        )}
      </Box>

      {/* Main content */}
      <Box flexGrow={1} flexDirection="column">
        {view === 'list' && (
          <SessionList
            sessions={sessions}
            selectedIndex={selectedIndex}
            onSelect={handleSessionSelect}
            onEnter={handleSessionEnter}
            active={modal === 'none'}
          />
        )}

        {view === 'detail' && selectedSession && (
          <SessionDetail session={selectedSession} />
        )}

        {!selectedSession && view === 'detail' && (
          <Box padding={1}>
            <Text dimColor>No session selected</Text>
          </Box>
        )}
      </Box>

      {/* Modals */}
      {modal === 'input' && selectedSession && (
        <InputPrompt
          slug={selectedSession.slug}
          onSubmit={handleInputSubmit}
          onCancel={() => setModal('none')}
        />
      )}

      {modal === 'create' && (
        <CreateModal
          activePaths={new Set(sessions.map((s) => s.path))}
          onSubmit={handleCreateSubmit}
          onCancel={() => setModal('none')}
        />
      )}

      {/* Status bar */}
      <StatusBar
        left="[j/k]nav [l]ist [d]etail [i]nput [n]ew [c]trl-C [x]delete [q]uit"
        right={`${sessions.length} sessions | ${waitingCount} waiting | ${workingCount} working`}
        connected={connected}
      />
    </Box>
  );
}
