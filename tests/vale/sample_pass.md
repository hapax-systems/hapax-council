# Building a Personal System

## Why I Built This

I built this system because I kept losing context between work sessions. Every morning started the same way: twenty minutes of archaeology through terminal history, git logs, and half-written notes. The system now handles that restoration automatically.

## How It Works

The architecture is simple. Agents read and write files on disk. An inotify watcher detects changes and cascades work through a pipeline. There is no message broker, no pub/sub complexity — just the filesystem.

### The Reactive Engine

When a file lands in a watched directory, the engine:

1. Parses the frontmatter for routing metadata
2. Matches against registered handlers
3. Dispatches work to the appropriate agent

Each step takes milliseconds. The whole pipeline from file-write to agent-response completes in under two seconds for most tasks.

### Why Filesystem Over Message Queues

Files are debuggable. You can `cat` them, `grep` them, version them with git. When something goes wrong, the evidence is right there on disk. Message queues hide their state behind APIs and require specialized tooling to inspect.

## What I Learned

The biggest surprise was how much simpler everything became once I stopped trying to build distributed systems patterns into a single-user tool. No consensus protocols, no leader election, no partition tolerance concerns. Just one person, one machine, reading and writing files.
