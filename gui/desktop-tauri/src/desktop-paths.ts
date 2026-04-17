import { open } from "@tauri-apps/plugin-dialog";
import {
  BaseDirectory,
  exists,
  mkdir,
  readTextFile,
  writeTextFile,
} from "@tauri-apps/plugin-fs";

import { isTauriRuntime, normalizePath } from "./mmo-sidecar";

const LOCAL_STORAGE_KEY = "mmo.desktop.recent-paths";
const RECENTS_PATH = "desktop/recent-paths.json";
const RECENT_LIMIT = 6;

export type RecentPathGroup =
  | "compareInputs"
  | "sceneLocksPaths"
  | "stemsDirs"
  | "workspaceDirs";

export type RecentPathsState = {
  compareInputs: string[];
  sceneLocksPaths: string[];
  stemsDirs: string[];
  version: 1;
  workspaceDirs: string[];
};

type BrowseFileOptions = {
  defaultPath?: string;
  extensions?: string[];
  label?: string;
  title: string;
};

function emptyRecentPaths(): RecentPathsState {
  return {
    compareInputs: [],
    sceneLocksPaths: [],
    stemsDirs: [],
    version: 1,
    workspaceDirs: [],
  };
}

function firstSelection(value: string | string[] | null): string | null {
  if (Array.isArray(value)) {
    return value[0] ?? null;
  }
  return value;
}

function sanitizeEntry(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  return normalizePath(trimmed);
}

function sanitizeList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const seen = new Set<string>();
  const result: string[] = [];
  for (const item of value) {
    const sanitized = sanitizeEntry(item);
    if (sanitized === null || seen.has(sanitized)) {
      continue;
    }
    seen.add(sanitized);
    result.push(sanitized);
    if (result.length >= RECENT_LIMIT) {
      break;
    }
  }
  return result;
}

function sanitizeRecentPaths(value: unknown): RecentPathsState {
  // Recent-path state is user convenience, not trusted config. Sanitize every
  // load so edited files or stale browser storage cannot poison desktop state.
  const source = value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Partial<Record<RecentPathGroup | "version", unknown>>
    : {};
  return {
    compareInputs: sanitizeList(source.compareInputs),
    sceneLocksPaths: sanitizeList(source.sceneLocksPaths),
    stemsDirs: sanitizeList(source.stemsDirs),
    version: 1,
    workspaceDirs: sanitizeList(source.workspaceDirs),
  };
}

async function writeBrowserRecentPaths(value: RecentPathsState): Promise<void> {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(value));
  } catch {
    // Best-effort fallback only.
  }
}

export async function loadRecentPaths(): Promise<RecentPathsState> {
  // Browser storage is only a fallback for tests and non-Tauri previews. The
  // packaged app prefers app-local data so recents survive WebView resets.
  if (!isTauriRuntime()) {
    if (typeof window === "undefined") {
      return emptyRecentPaths();
    }
    try {
      const raw = window.localStorage.getItem(LOCAL_STORAGE_KEY);
      return raw === null ? emptyRecentPaths() : sanitizeRecentPaths(JSON.parse(raw));
    } catch {
      return emptyRecentPaths();
    }
  }

  try {
    const hasFile = await exists(RECENTS_PATH, { baseDir: BaseDirectory.AppLocalData });
    if (!hasFile) {
      return emptyRecentPaths();
    }
    const raw = await readTextFile(RECENTS_PATH, { baseDir: BaseDirectory.AppLocalData });
    return sanitizeRecentPaths(JSON.parse(raw));
  } catch {
    return emptyRecentPaths();
  }
}

export async function saveRecentPaths(value: RecentPathsState): Promise<void> {
  const sanitized = sanitizeRecentPaths(value);
  // Write the same sanitized shape to every backend so desktop and browser
  // fallback paths do not drift into different recent-path rules.
  if (!isTauriRuntime()) {
    await writeBrowserRecentPaths(sanitized);
    return;
  }

  try {
    await mkdir("desktop", {
      baseDir: BaseDirectory.AppLocalData,
      recursive: true,
    });
    await writeTextFile(
      RECENTS_PATH,
      `${JSON.stringify(sanitized, null, 2)}\n`,
      { baseDir: BaseDirectory.AppLocalData },
    );
  } catch {
    await writeBrowserRecentPaths(sanitized);
  }
}

export function recordRecentPath(
  current: RecentPathsState,
  group: RecentPathGroup,
  value: string,
): RecentPathsState {
  const sanitized = sanitizeEntry(value);
  if (sanitized === null) {
    return current;
  }

  // Keep recents short and newest-first. The UI treats this as a launch aid,
  // not an audit log that keeps duplicate or long-tail entries forever.
  const next = current[group].filter((entry) => entry !== sanitized);
  return {
    ...current,
    [group]: [sanitized, ...next].slice(0, RECENT_LIMIT),
  };
}

export async function browseDirectory(options: {
  defaultPath?: string;
  title: string;
}): Promise<string | null> {
  // Host file pickers are a desktop-only privilege. Returning null here keeps
  // browser previews from pretending they can browse the local filesystem.
  if (!isTauriRuntime()) {
    return null;
  }

  const selection = await open({
    defaultPath: options.defaultPath,
    directory: true,
    recursive: false,
    title: options.title,
  });
  return firstSelection(selection);
}

export async function browseFile(options: BrowseFileOptions): Promise<string | null> {
  // Mirror the desktop-only rule for file picks so tests and Vite preview do
  // not silently diverge from the packaged app's trust boundary.
  if (!isTauriRuntime()) {
    return null;
  }

  const selection = await open({
    defaultPath: options.defaultPath,
    filters: options.extensions === undefined
      ? undefined
      : [{
        extensions: options.extensions,
        name: options.label ?? "Files",
      }],
    title: options.title,
  });
  return firstSelection(selection);
}
