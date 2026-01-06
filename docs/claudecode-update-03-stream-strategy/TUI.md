# Ink: React for Terminal UIs

## What is Ink?

[Ink](https://github.com/vadimdemedes/ink) is a React renderer for the terminal. Instead of rendering to the DOM, it renders to the terminal using ANSI escape codes. You write components with JSX, use hooks like `useState` and `useEffect`, and get a reactive terminal UI.

**Why Ink for CBOS?**

|Consideration        |Ink                       |Python Textual |Raw Node blessed/ncurses|
|---------------------|--------------------------|---------------|------------------------|
|Language alignment   |TypeScript ✓              |Python ✗       |JS/C ✓                  |
|Claude Code ecosystem|Node.js native            |Foreign runtime|Low-level               |
|Component model      |React (familiar)          |Widget classes |Imperative              |
|State management     |Hooks, context            |Reactive attrs |Manual                  |
|Testing              |Jest + ink-testing-library|pytest         |Difficult               |
|Hot reload           |✓                         |✓              |✗                       |

Since you’re moving CBOS to TypeScript and Claude Code is Node.js-based, Ink is the natural fit.

-----

## Core Concepts

### Basic App Structure

```tsx
import React, { useState, useEffect } from 'react';
import { render, Box, Text, useInput, useApp } from 'ink';

const App = () => {
  const [count, setCount] = useState(0);
  const { exit } = useApp();

  useInput((input, key) => {
    if (input === 'q') exit();
    if (key.return) setCount(c => c + 1);
  });

  return (
    <Box flexDirection="column" padding={1}>
      <Text color="green">CBOS Session Manager</Text>
      <Text>Press Enter to increment: {count}</Text>
      <Text dimColor>Press q to quit</Text>
    </Box>
  );
};

render(<App />);
```

### Layout with Flexbox

Ink uses Yoga (Facebook’s flexbox implementation) for layout:

```tsx
<Box flexDirection="row" justifyContent="space-between">
  <Box width="30%">
    <Text>Sidebar</Text>
  </Box>
  <Box width="70%" borderStyle="single" borderColor="blue">
    <Text>Main Content</Text>
  </Box>
</Box>
```

### Built-in Components

|Component    |Purpose                         |
|-------------|--------------------------------|
|`<Box>`      |Flexbox container (like `<div>`)|
|`<Text>`     |Styled text output              |
|`<Newline>`  |Line break                      |
|`<Spacer>`   |Flexible space (like `flex: 1`) |
|`<Static>`   |Non-updating content (logs)     |
|`<Transform>`|Text transformation             |

### Hooks

|Hook               |Purpose                   |
|-------------------|--------------------------|
|`useInput(handler)`|Keyboard input            |
|`useApp()`         |App control (`exit()`)    |
|`useStdin()`       |Raw stdin access          |
|`useStdout()`      |Stdout dimensions         |
|`useFocus()`       |Focus management          |
|`useFocusManager()`|Programmatic focus control|

-----

## Key Libraries for CBOS

### ink-spinner

Loading indicators:

```tsx
import Spinner from 'ink-spinner';
<Text><Spinner type="dots" /> Processing...</Text>
```

### ink-text-input

User text input:

```tsx
import TextInput from 'ink-text-input';
const [query, setQuery] = useState('');
<TextInput value={query} onChange={setQuery} onSubmit={handleSubmit} />
```

### ink-select-input

Selection menus:

```tsx
import SelectInput from 'ink-select-input';
const items = [
  { label: 'Session 1', value: 's1' },
  { label: 'Session 2', value: 's2' },
];
<SelectInput items={items} onSelect={item => console.log(item.value)} />
```

### ink-table

Data tables:

```tsx
import Table from 'ink-table';
const data = [
  { session: 'abc123', status: 'waiting', messages: 42 },
  { session: 'def456', status: 'working', messages: 17 },
];
<Table data={data} />
```

### ink-big-text

ASCII art headers:

```tsx
import BigText from 'ink-big-text';
<BigText text="CBOS" font="chrome" />
```

### ink-gradient

Gradient text:

```tsx
import Gradient from 'ink-gradient';
<Gradient name="rainbow"><BigText text="CBOS" /></Gradient>
```

-----

## CBOS TUI Architecture

### Proposed Structure

```
packages/cbos-tui/
├── src/
│   ├── index.tsx              # Entry point
│   ├── App.tsx                # Root component
│   ├── components/
│   │   ├── SessionList.tsx    # Session table/list
│   │   ├── SessionDetail.tsx  # Single session view
│   │   ├── StatusBar.tsx      # Bottom status bar
│   │   ├── InputPrompt.tsx    # Command input
│   │   ├── LogViewer.tsx      # Scrollable log output
│   │   └── Header.tsx         # Top bar with title
│   ├── hooks/
│   │   ├── useSessionManager.ts   # Session state
│   │   ├── useEventStream.ts      # Watch events.jsonl
│   │   ├── useKeyBindings.ts      # Global hotkeys
│   │   └── useClaudeSDK.ts        # SDK integration
│   ├── store/
│   │   └── sessions.ts        # Zustand store (optional)
│   └── utils/
│       ├── formatting.ts      # Text truncation, etc.
│       └── colors.ts          # Theme colors
├── package.json
└── tsconfig.json
```

### State Management Options

**Option A: React Context + useReducer**

```tsx
const SessionContext = createContext<SessionState>(null);

function sessionReducer(state, action) {
  switch (action.type) {
    case 'SESSION_WAITING':
      return { ...state, [action.sessionId]: { ...state[action.sessionId], status: 'waiting' } };
    // ...
  }
}

const App = () => {
  const [state, dispatch] = useReducer(sessionReducer, {});
  return (
    <SessionContext.Provider value={{ state, dispatch }}>
      <Dashboard />
    </SessionContext.Provider>
  );
};
```

**Option B: Zustand (simpler)**

```tsx
import { create } from 'zustand';

interface SessionStore {
  sessions: Map<string, Session>;
  setSessionStatus: (id: string, status: Status) => void;
}

const useSessionStore = create<SessionStore>((set) => ({
  sessions: new Map(),
  setSessionStatus: (id, status) => set((state) => {
    const sessions = new Map(state.sessions);
    const session = sessions.get(id);
    if (session) sessions.set(id, { ...session, status });
    return { sessions };
  }),
}));
```

-----

## Implementation Plan

### Phase 1: Skeleton App (Week 1)

**Goal**: Basic TUI shell with navigation

```tsx
// App.tsx
import React, { useState } from 'react';
import { Box, Text, useInput } from 'ink';
import { Header } from './components/Header';
import { SessionList } from './components/SessionList';
import { StatusBar } from './components/StatusBar';

type View = 'list' | 'detail' | 'logs';

export const App = () => {
  const [view, setView] = useState<View>('list');
  const [selectedSession, setSelectedSession] = useState<string | null>(null);

  useInput((input, key) => {
    if (input === 'l') setView('list');
    if (input === 'd' && selectedSession) setView('detail');
    if (key.escape) setView('list');
  });

  return (
    <Box flexDirection="column" height="100%">
      <Header title="CBOS" subtitle={view} />
      
      <Box flexGrow={1}>
        {view === 'list' && (
          <SessionList 
            onSelect={(id) => {
              setSelectedSession(id);
              setView('detail');
            }} 
          />
        )}
        {view === 'detail' && selectedSession && (
          <SessionDetail sessionId={selectedSession} />
        )}
      </Box>
      
      <StatusBar 
        left="[L]ist [D]etail [Q]uit"
        right={`Sessions: 3 | Waiting: 1`}
      />
    </Box>
  );
};
```

**Tasks**:

- [ ] Set up monorepo with `packages/cbos-tui`
- [ ] Create basic App shell
- [ ] Implement Header, StatusBar components
- [ ] Add keyboard navigation
- [ ] Mock session data

### Phase 2: Event Integration (Week 2)

**Goal**: Connect to real Claude Code events

```tsx
// hooks/useEventStream.ts
import { useState, useEffect } from 'react';
import { watch } from 'fs';
import { createReadStream } from 'fs';
import { createInterface } from 'readline';

interface WaitingEvent {
  event: 'waiting_for_input';
  session: { id: string; transcript_path: string };
  context: { preceding_text: string };
  timestamp: string;
}

export function useEventStream(eventLogPath: string) {
  const [events, setEvents] = useState<WaitingEvent[]>([]);
  const [lastPosition, setLastPosition] = useState(0);

  useEffect(() => {
    const processNewLines = async () => {
      const rl = createInterface({
        input: createReadStream(eventLogPath, { start: lastPosition }),
      });

      for await (const line of rl) {
        if (!line.trim()) continue;
        try {
          const event = JSON.parse(line) as WaitingEvent;
          setEvents(prev => [...prev, event]);
          setLastPosition(pos => pos + Buffer.byteLength(line) + 1);
        } catch {}
      }
    };

    const watcher = watch(eventLogPath, (eventType) => {
      if (eventType === 'change') processNewLines();
    });

    processNewLines(); // Initial read

    return () => watcher.close();
  }, [eventLogPath]);

  return events;
}
```

**Tasks**:

- [ ] Implement `useEventStream` hook
- [ ] Parse and validate event schema
- [ ] Update SessionList from events
- [ ] Add real-time status indicators (spinners, colors)

### Phase 3: Session Management (Week 3)

**Goal**: View, control, and interact with sessions

```tsx
// components/SessionDetail.tsx
import React from 'react';
import { Box, Text, Newline } from 'ink';
import Spinner from 'ink-spinner';
import { useSession } from '../hooks/useSessionManager';

interface Props {
  sessionId: string;
}

export const SessionDetail = ({ sessionId }: Props) => {
  const session = useSession(sessionId);

  if (!session) {
    return <Text color="red">Session not found</Text>;
  }

  return (
    <Box flexDirection="column" padding={1}>
      <Box marginBottom={1}>
        <Text bold color="cyan">Session: </Text>
        <Text>{session.id}</Text>
      </Box>

      <Box marginBottom={1}>
        <Text bold>Status: </Text>
        {session.status === 'working' ? (
          <Text color="yellow"><Spinner type="dots" /> Working</Text>
        ) : session.status === 'waiting' ? (
          <Text color="green">● Waiting for input</Text>
        ) : (
          <Text color="gray">○ Idle</Text>
        )}
      </Box>

      <Box marginBottom={1}>
        <Text bold>Messages: </Text>
        <Text>{session.messageCount}</Text>
      </Box>

      <Box flexDirection="column" borderStyle="single" borderColor="gray" padding={1}>
        <Text bold dimColor>Last Response:</Text>
        <Newline />
        <Text wrap="wrap">{session.lastResponse || '(none)'}</Text>
      </Box>
    </Box>
  );
};
```

**Tasks**:

- [ ] Implement SessionDetail component
- [ ] Add scrollable log viewer (ink-scroll-area or custom)
- [ ] Show transcript content
- [ ] Add action buttons (inject input, kill, restart)

### Phase 4: Input Injection (Week 4)

**Goal**: Send input to waiting sessions

```tsx
// hooks/useClaudeSDK.ts
import { query } from '@anthropic-ai/claude-code';

export function useSessionControl() {
  const injectInput = async (sessionId: string, message: string) => {
    // Use --continue with session ID
    const result = await query({
      prompt: message,
      options: {
        continue: sessionId,
        // Or use resume with full session ID
      }
    });
    return result;
  };

  const killSession = async (sessionId: string) => {
    // Send interrupt signal or use SDK method
  };

  return { injectInput, killSession };
}
```

```tsx
// components/InputPrompt.tsx
import React, { useState } from 'react';
import { Box, Text } from 'ink';
import TextInput from 'ink-text-input';

interface Props {
  sessionId: string;
  onSubmit: (message: string) => void;
}

export const InputPrompt = ({ sessionId, onSubmit }: Props) => {
  const [value, setValue] = useState('');

  const handleSubmit = () => {
    if (value.trim()) {
      onSubmit(value);
      setValue('');
    }
  };

  return (
    <Box>
      <Text color="cyan">{sessionId.slice(0, 8)}❯ </Text>
      <TextInput
        value={value}
        onChange={setValue}
        onSubmit={handleSubmit}
        placeholder="Type message to inject..."
      />
    </Box>
  );
};
```

**Tasks**:

- [ ] Integrate Claude Agent SDK
- [ ] Implement input injection
- [ ] Add command history (up/down arrows)
- [ ] Handle errors gracefully

### Phase 5: Multi-Session View (Week 5)

**Goal**: Monitor multiple sessions simultaneously

```tsx
// components/MultiSessionView.tsx
import React from 'react';
import { Box, Text } from 'ink';
import { useSessionStore } from '../store/sessions';

export const MultiSessionView = () => {
  const sessions = useSessionStore(state => 
    Array.from(state.sessions.values())
  );

  const columns = Math.min(sessions.length, 3);

  return (
    <Box flexDirection="row" flexWrap="wrap">
      {sessions.map(session => (
        <Box 
          key={session.id}
          width={`${100 / columns}%`}
          borderStyle="single"
          borderColor={session.status === 'waiting' ? 'green' : 'gray'}
          padding={1}
        >
          <Box flexDirection="column">
            <Text bold>{session.id.slice(0, 12)}</Text>
            <Text color={session.status === 'waiting' ? 'green' : 'yellow'}>
              {session.status}
            </Text>
            <Text dimColor wrap="truncate-end">
              {session.lastResponse?.slice(0, 100)}
            </Text>
          </Box>
        </Box>
      ))}
    </Box>
  );
};
```

**Tasks**:

- [ ] Grid/tile layout for multiple sessions
- [ ] Focus management between tiles
- [ ] Aggregate status bar (X waiting, Y working)
- [ ] Quick actions per tile

### Phase 6: Polish & Features (Week 6+)

- [ ] Configuration file support
- [ ] Themes/color schemes
- [ ] Search/filter sessions
- [ ] Export session transcripts
- [ ] Keyboard shortcut help overlay
- [ ] Error boundaries
- [ ] Logging to file
- [ ] Unit tests with ink-testing-library

-----

## Example: Complete Session List Component

```tsx
// components/SessionList.tsx
import React from 'react';
import { Box, Text, useFocus } from 'ink';
import SelectInput from 'ink-select-input';
import Spinner from 'ink-spinner';
import { useSessionStore } from '../store/sessions';
import { formatDistanceToNow } from 'date-fns';

interface Props {
  onSelect: (sessionId: string) => void;
}

export const SessionList = ({ onSelect }: Props) => {
  const sessions = useSessionStore(state => 
    Array.from(state.sessions.values())
      .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime())
  );

  if (sessions.length === 0) {
    return (
      <Box padding={2}>
        <Text dimColor>No active sessions. Start Claude Code in another terminal.</Text>
      </Box>
    );
  }

  const items = sessions.map(session => ({
    label: formatSessionLabel(session),
    value: session.id,
  }));

  return (
    <Box flexDirection="column" padding={1}>
      <Box marginBottom={1}>
        <Text bold>Sessions</Text>
        <Text dimColor> ({sessions.length})</Text>
      </Box>
      
      <SelectInput
        items={items}
        onSelect={item => onSelect(item.value)}
        itemComponent={SessionItem}
      />
    </Box>
  );
};

const SessionItem = ({ isSelected, label }) => (
  <Text color={isSelected ? 'cyan' : undefined}>
    {isSelected ? '❯ ' : '  '}{label}
  </Text>
);

function formatSessionLabel(session: Session): string {
  const status = session.status === 'waiting' 
    ? '●' 
    : session.status === 'working' 
      ? '◐' 
      : '○';
  
  const statusColor = session.status === 'waiting' ? 'green' : 'yellow';
  const time = formatDistanceToNow(new Date(session.updatedAt), { addSuffix: true });
  
  return `${status} ${session.id.slice(0, 12)}  ${session.messageCount} msgs  ${time}`;
}
```

-----

## Running the TUI

```bash
# Development
cd packages/cbos-tui
npm run dev

# Production build
npm run build
npm start

# Or as global CLI
npm link
cbos-tui
```

**package.json**:

```json
{
  "name": "@cbos/tui",
  "version": "0.1.0",
  "type": "module",
  "bin": {
    "cbos-tui": "./dist/index.js"
  },
  "scripts": {
    "dev": "tsx watch src/index.tsx",
    "build": "tsup src/index.tsx --format esm",
    "start": "node dist/index.js"
  },
  "dependencies": {
    "ink": "^4.4.1",
    "ink-select-input": "^5.0.0",
    "ink-spinner": "^5.0.0",
    "ink-text-input": "^5.0.1",
    "react": "^18.2.0",
    "zustand": "^4.4.0",
    "date-fns": "^3.0.0"
  },
  "devDependencies": {
    "@types/react": "^18.2.0",
    "tsx": "^4.0.0",
    "tsup": "^8.0.0",
    "typescript": "^5.3.0"
  }
}
```

-----

## Summary

|Week|Milestone                   |
|----|----------------------------|
|1   |Skeleton app with navigation|
|2   |Event stream integration    |
|3   |Session detail view         |
|4   |Input injection via SDK     |
|5   |Multi-session dashboard     |
|6+  |Polish, tests, features     |

Ink gives you React’s component model in the terminal, which pairs naturally with your TypeScript CBOS rewrite and the Node.js Claude Code ecosystem.
