#!/usr/bin/env python3
"""
Verbose WebSocket listener for watching CBOS session events.

Usage:
    python -m orchestrator.watch
    python -m orchestrator.watch --raw  # Show raw JSON
"""

import asyncio
import json
from datetime import datetime

import websockets
from rich.console import Console
from rich.panel import Panel

console = Console()

# Event category icons and colors
CATEGORY_STYLES = {
    "init": ("▶", "dim"),
    "thinking": ("◐", "yellow"),
    "text": ("💬", "white"),
    "tool_use": ("⚙", "cyan"),
    "tool_result": ("✓", "green"),
    "result": ("●", "blue"),
    "error": ("✗", "red"),
    "waiting": ("⏳", "magenta"),
    "question": ("❓", "yellow bold"),
    "system": ("⚡", "dim"),
    "compact": ("📦", "magenta"),
    "user_msg": ("👤", "green"),
    "unknown": ("·", "dim"),
}

# State icons
STATE_STYLES = {
    "idle": ("○", "dim"),
    "thinking": ("◐", "yellow"),
    "working": ("◑", "cyan"),
    "waiting": ("●", "red"),
    "error": ("✗", "red"),
}


def format_timestamp():
    """Get formatted timestamp"""
    return datetime.now().strftime("%H:%M:%S")


def print_event(slug: str, event: dict, raw: bool = False):
    """Print a formatted event"""
    ts = format_timestamp()
    category = event.get("category", "unknown")
    icon, color = CATEGORY_STYLES.get(category, ("·", "dim"))
    summary = event.get("summary", "")[:80]

    if raw:
        console.print(
            f"[dim]{ts}[/] [{color}]{icon}[/] [cyan][{slug}][/] {json.dumps(event)}"
        )
    else:
        console.print(f"[dim]{ts}[/] [{color}]{icon}[/] [cyan][{slug}][/] {summary}")

    # Extra details for questions
    if category == "question":
        options = event.get("questionOptions", [])
        if options:
            console.print(
                f"         Options: {', '.join(options[:4])}", style="yellow dim"
            )
        details = event.get("details", "")
        if details and len(details) > len(summary):
            console.print(f"         {details[:200]}", style="dim")


def print_session_update(session: dict):
    """Print session state update"""
    ts = format_timestamp()
    slug = session.get("slug", "?")
    state = session.get("state", "unknown")
    icon, color = STATE_STYLES.get(state, ("?", "white"))
    msg_count = session.get("messageCount", 0)

    console.print(
        f"[dim]{ts}[/] [{color}]{icon}[/] [cyan][{slug}][/] state={state} msgs={msg_count}"
    )


def print_raw(msg_type: str, data: dict):
    """Print raw message"""
    ts = format_timestamp()
    console.print(f"[dim]{ts}[/] [magenta]{msg_type}[/]: {json.dumps(data, indent=2)}")


async def watch(
    ws_url: str = "ws://localhost:32205", raw: bool = False, verbose: bool = True
):
    """Watch WebSocket events"""

    console.print(
        Panel.fit(
            f"[bold]CBOS Event Watcher[/bold]\n"
            f"Connecting to: [cyan]{ws_url}[/cyan]\n"
            f"Raw mode: {raw} | Verbose: {verbose}",
            border_style="blue",
        )
    )

    try:
        async with websockets.connect(ws_url) as ws:
            # Subscribe to all sessions
            await ws.send(json.dumps({"type": "subscribe", "sessions": ["*"]}))

            console.print("[green]Connected![/green] Watching for events...\n")

            async for message in ws:
                try:
                    msg = json.loads(message)
                    msg_type = msg.get("type", "unknown")

                    if raw:
                        print_raw(msg_type, msg)
                        continue

                    if msg_type == "sessions":
                        # Initial session list
                        sessions = msg.get("sessions", [])
                        console.print(
                            f"[dim]{format_timestamp()}[/] [blue]●[/] Received {len(sessions)} sessions"
                        )
                        for s in sessions:
                            slug = s.get("slug", "?")
                            state = s.get("state", "?")
                            icon, color = STATE_STYLES.get(state, ("?", "white"))
                            console.print(
                                f"         [{color}]{icon}[/] {slug}: {state}"
                            )

                    elif msg_type == "formatted_event":
                        slug = msg.get("slug", "?")
                        event = msg.get("event", {})
                        print_event(slug, event, raw=False)

                    elif msg_type == "session_update":
                        if verbose:
                            session = msg.get("session", {})
                            print_session_update(session)

                    elif msg_type == "session_waiting":
                        slug = msg.get("slug", "?")
                        context = msg.get("context", "")[:100]
                        console.print(
                            f"[dim]{format_timestamp()}[/] [magenta]⏳[/] [cyan][{slug}][/] "
                            f"[bold]WAITING FOR INPUT[/bold]"
                        )
                        if context:
                            console.print(
                                f"         Context: {context}...", style="dim"
                            )

                    elif msg_type == "session_created":
                        session = msg.get("session", {})
                        slug = session.get("slug", "?")
                        path = session.get("path", "?")
                        console.print(
                            f"[dim]{format_timestamp()}[/] [green]+[/] [cyan][{slug}][/] "
                            f"Session created: {path}"
                        )

                    elif msg_type == "session_deleted":
                        slug = msg.get("slug", "?")
                        console.print(
                            f"[dim]{format_timestamp()}[/] [red]-[/] [cyan][{slug}][/] "
                            f"Session deleted"
                        )

                    elif msg_type == "error":
                        error_msg = msg.get("message", "Unknown error")
                        console.print(
                            f"[dim]{format_timestamp()}[/] [red]ERROR[/]: {error_msg}"
                        )

                    elif verbose:
                        console.print(
                            f"[dim]{format_timestamp()}[/] [dim]{msg_type}[/]: {str(msg)[:100]}"
                        )

                except json.JSONDecodeError as e:
                    console.print(f"[red]JSON error:[/] {e}")
                except Exception as e:
                    console.print(f"[red]Error:[/] {e}")

    except websockets.ConnectionClosed:
        console.print("[yellow]Connection closed[/yellow]")
    except ConnectionRefusedError:
        console.print("[red]Connection refused - is CBOS server running?[/red]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Watch CBOS WebSocket events")
    parser.add_argument("-p", "--port", type=int, default=32205, help="WebSocket port")
    parser.add_argument("--raw", action="store_true", help="Show raw JSON messages")
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Hide session updates"
    )
    args = parser.parse_args()

    try:
        asyncio.run(
            watch(
                ws_url=f"ws://localhost:{args.port}",
                raw=args.raw,
                verbose=not args.quiet,
            )
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped[/yellow]")


if __name__ == "__main__":
    main()
