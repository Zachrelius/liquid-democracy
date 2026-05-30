"""WA3 — At-Desk Dashboard.

Local web dashboard for watching the live Claude Code work stream +
the WA1 planner state + a chat box into the WA1 IPC inbox + quota /
model / cost panel.

Self-contained: FastAPI + WebSocket server + one HTML page. Binds to
127.0.0.1 only. Reads (read-only) the WA1 state dir; writes (write-
only) to the WA1 IPC inbox per contract v1.

Run via the CLI::

    python -m dashboard.cli serve \\
        --port 8765 \\
        --state-dir <path> \\
        --ipc-root <path>

See ``hook_handler.py`` for the script Claude Code hooks invoke to
forward events into the dashboard. See ``stub_responder.py`` for the
WA4-stand-in process that echoes inbox messages back to the outbox
so the chat round-trip can be exercised end-to-end before WA4 exists.
"""

PORT = 8765
HOST = "127.0.0.1"
