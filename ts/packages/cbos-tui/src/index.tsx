#!/usr/bin/env node

import React from 'react';
import { render } from 'ink';
import { App } from './App.js';

// Clear screen and render
console.clear();

const { waitUntilExit } = render(<App />);

waitUntilExit().then(() => {
  process.exit(0);
});
