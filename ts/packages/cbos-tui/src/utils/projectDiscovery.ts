import { execSync } from 'child_process';
import { readFileSync, statSync, existsSync } from 'fs';
import { join, dirname } from 'path';
import { homedir } from 'os';

export interface Project {
  path: string;
  name: string;
  mtime: number;
  display: string;
}

/**
 * Generate session name from git remote origin URL.
 * Falls back to directory name if git config not available.
 */
function generateSessionName(projectDir: string): string {
  const gitConfig = join(projectDir, '.git', 'config');

  if (existsSync(gitConfig)) {
    try {
      const content = readFileSync(gitConfig, 'utf-8');
      for (const line of content.split('\n')) {
        if (line.includes('url =')) {
          // Extract URL and get repo name
          const url = line.split('=').pop()?.trim() ?? '';
          // Handle various URL formats:
          // git@github.com:user/repo.git
          // https://github.com/user/repo.git
          let repoName = url.split('/').pop() ?? '';
          if (repoName.endsWith('.git')) {
            repoName = repoName.slice(0, -4);
          }
          return repoName.toUpperCase();
        }
      }
    } catch {
      // Fall through to directory name
    }
  }

  // Fallback to directory name
  return projectDir.split('/').pop()?.toUpperCase() ?? 'UNKNOWN';
}

/**
 * Discover Claude projects by finding CLAUDE.md files.
 * Returns list sorted by mtime desc (most recent first).
 * Filters out paths that are already active sessions.
 */
export function discoverClaudeProjects(activePaths: Set<string>): Project[] {
  const home = homedir();
  const projects: Project[] = [];

  try {
    // Find all CLAUDE.md files (exclude hidden directories)
    const result = execSync(
      `find "${home}" -type f -name "CLAUDE.md" -not -path "*/.*" 2>/dev/null`,
      { encoding: 'utf-8', timeout: 30000 }
    );

    for (const line of result.trim().split('\n')) {
      if (!line) continue;

      const claudeMd = line;
      const projectDir = dirname(claudeMd);

      // Skip if already an active session
      if (activePaths.has(projectDir)) continue;

      // Get modification time
      let mtime: number;
      try {
        mtime = statSync(claudeMd).mtimeMs;
      } catch {
        continue;
      }

      // Generate session name from git config
      const sessionName = generateSessionName(projectDir);

      projects.push({
        path: projectDir,
        name: sessionName,
        mtime,
        display: `${sessionName} (${projectDir})`,
      });
    }

    // Sort by mtime descending (most recent first)
    projects.sort((a, b) => b.mtime - a.mtime);
  } catch {
    // Ignore errors (timeout, find not found, etc.)
  }

  return projects;
}
