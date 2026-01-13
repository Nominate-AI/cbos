#!/usr/bin/env python3
"""CLI for CBOS pattern management"""

import argparse
import asyncio
import json
from datetime import datetime

from rich.console import Console
from rich.table import Table

from .extractor import DecisionPatternExtractor
from .models import QuestionType
from .skill_registry import get_registry
from .store import PatternStore

console = Console()


def parse_date(date_str: str) -> datetime:
    """Parse date string to datetime"""
    if not date_str:
        return None
    return datetime.fromisoformat(date_str)


async def cmd_build(args):
    """Build pattern database from conversation logs"""
    console.print("[bold blue]Building pattern database...[/bold blue]")

    # Create extractor
    extractor = DecisionPatternExtractor(
        project_filter=args.project,
        after_date=parse_date(args.after) if args.after else None,
        before_date=parse_date(args.before) if args.before else None,
        include_thinking=True,
    )

    # Extract patterns
    console.print("Extracting patterns from conversation logs...")
    patterns = list(extractor.extract_patterns())
    console.print(f"Found [green]{len(patterns)}[/green] patterns")

    if not patterns:
        console.print("[yellow]No patterns found. Check your filters.[/yellow]")
        return

    # Add to store
    store = PatternStore()
    store.connect()

    console.print(f"Adding patterns to database (batch size: {args.batch_size})...")

    if args.no_embeddings:
        added = await store.add_patterns_batch(
            patterns, batch_size=args.batch_size, generate_embeddings=False
        )
    else:
        console.print("[dim]Generating embeddings via CBAI...[/dim]")
        added = await store.add_patterns_batch(
            patterns, batch_size=args.batch_size, generate_embeddings=True
        )

    store.close()

    console.print(f"[bold green]Added {added} patterns to database[/bold green]")


async def cmd_query(args):
    """Query similar patterns"""
    store = PatternStore()
    store.connect()

    # Check if we have embeddings
    stats = store.get_stats()
    if stats.patterns_with_embeddings == 0:
        console.print(
            "[yellow]No embeddings in database. Run 'cbos-patterns build' first.[/yellow]"
        )
        store.close()
        return

    console.print(f"Querying: [cyan]{args.text}[/cyan]")

    question_type = None
    if args.type:
        try:
            question_type = QuestionType(args.type)
        except ValueError:
            console.print(f"[red]Invalid question type: {args.type}[/red]")
            store.close()
            return

    matches = await store.query_similar_text(
        query_text=args.text,
        threshold=args.threshold,
        max_results=args.limit,
        question_type=question_type,
        project_filter=args.project,
    )

    store.close()

    if not matches:
        console.print("[yellow]No similar patterns found.[/yellow]")
        return

    if args.json:
        output = [
            {
                "similarity": m.similarity,
                "question": m.pattern.question_text,
                "answer": m.pattern.user_answer,
                "type": m.pattern.question_type.value,
                "project": m.pattern.project,
            }
            for m in matches
        ]
        print(json.dumps(output, indent=2))
    else:
        table = Table(title=f"Similar Patterns (threshold: {args.threshold})")
        table.add_column("Score", style="cyan", width=8)
        table.add_column("Question", style="white", max_width=50)
        table.add_column("Answer", style="green", max_width=30)
        table.add_column("Type", style="yellow", width=12)

        for match in matches:
            q_text = match.pattern.question_text
            if len(q_text) > 50:
                q_text = q_text[:47] + "..."

            a_text = match.pattern.user_answer
            if len(a_text) > 30:
                a_text = a_text[:27] + "..."

            table.add_row(
                f"{match.similarity:.1%}",
                q_text,
                a_text,
                match.pattern.question_type.value,
            )

        console.print(table)


def cmd_stats(args):
    """Show pattern statistics"""
    store = PatternStore()
    store.connect()
    stats = store.get_stats()
    vector_stats = store.get_vector_stats()
    store.close()

    if args.json:
        output = {
            "total_patterns": stats.total_patterns,
            "patterns_with_embeddings": stats.patterns_with_embeddings,
            "question_types": stats.question_types,
            "projects": stats.projects,
            "date_range": stats.date_range,
            "vector_store": vector_stats,
        }
        print(json.dumps(output, indent=2))
    else:
        console.print("[bold]Pattern Database Statistics[/bold]\n")

        console.print(f"Total patterns: [cyan]{stats.total_patterns}[/cyan]")
        console.print(f"With embeddings: [cyan]{stats.patterns_with_embeddings}[/cyan]")

        # Vector store info
        console.print("\n[bold]Vector Store (vectl):[/bold]")
        console.print(f"  Path: [dim]{vector_stats['store_path']}[/dim]")
        console.print(f"  Dimensions: [cyan]{vector_stats['vector_dim']}[/cyan]")
        console.print(f"  Clusters: [cyan]{vector_stats['num_clusters']}[/cyan]")
        console.print(f"  File size: [cyan]{vector_stats['file_size_mb']} MB[/cyan]")
        console.print(
            f"  Connected: [{'green' if vector_stats['is_connected'] else 'red'}]{vector_stats['is_connected']}[/]"
        )

        if stats.date_range[0]:
            console.print(
                f"\nDate range: [dim]{stats.date_range[0][:10]} to {stats.date_range[1][:10]}[/dim]"
            )

        if stats.question_types:
            console.print("\n[bold]By Question Type:[/bold]")
            for qtype, count in sorted(
                stats.question_types.items(), key=lambda x: x[1], reverse=True
            ):
                console.print(f"  {qtype}: [green]{count}[/green]")

        if stats.projects:
            console.print("\n[bold]Top Projects:[/bold]")
            for project, count in list(stats.projects.items())[:10]:
                # Shorten project path for display
                short_project = project
                if len(project) > 40:
                    short_project = "..." + project[-37:]
                console.print(f"  {short_project}: [green]{count}[/green]")


async def cmd_listen(args):
    """Listen to CBOS sessions and match patterns in real-time"""
    from .listener import OrchestratorListener

    console.print("[bold blue]Starting orchestrator listener...[/bold blue]")
    console.print(f"Connecting to: [cyan]ws://localhost:{args.port}[/cyan]")
    console.print(
        f"Auto-answer: [{'green' if args.auto_answer else 'yellow'}]{args.auto_answer}[/]"
    )
    console.print(f"Auto-answer threshold: [cyan]{args.auto_threshold:.0%}[/cyan]")
    console.print(f"Suggestion threshold: [cyan]{args.suggest_threshold:.0%}[/cyan]")
    console.print(
        f"Skill detection: [{'green' if args.skills else 'yellow'}]{args.skills}[/]"
    )
    if args.skills:
        console.print(f"Skill threshold: [cyan]{args.skill_threshold:.0%}[/cyan]")
    console.print()

    listener = OrchestratorListener(
        ws_url=f"ws://localhost:{args.port}",
        auto_answer_threshold=args.auto_threshold,
        suggestion_threshold=args.suggest_threshold,
        skill_threshold=args.skill_threshold,
        auto_answer_enabled=args.auto_answer,
        skill_detection_enabled=args.skills,
    )

    # Set up callbacks for display
    async def on_connect():
        console.print("[green]Connected to CBOS server[/green]")

    async def on_disconnect():
        console.print("[yellow]Disconnected from CBOS server[/yellow]")

    async def on_question(event):
        console.print(
            f"[cyan][{event.slug}][/cyan] Question: {event.question_text[:70]}..."
        )
        if event.options:
            console.print(f"  Options: {', '.join(event.options[:4])}")

    async def on_suggestion(slug, answer, similarity):
        console.print(
            f"[yellow][{slug}][/yellow] Suggestion ({similarity:.0%}): {answer[:50]}..."
        )

    async def on_auto_answer(slug, answer):
        console.print(f"[green][{slug}][/green] Auto-answered: {answer}")

    async def on_session_update(update):
        if args.verbose:
            console.print(
                f"[dim][{update.slug}] state={update.state} msgs={update.message_count}[/dim]"
            )

    async def on_skill_match(match):
        console.print(
            f"[magenta][{match.slug}][/magenta] Skill: {match.skill_name} "
            f"({match.confidence:.0%})"
        )
        if match.extracted_params:
            params_str = ", ".join(
                f"{k}={v}" for k, v in match.extracted_params.items()
            )
            console.print(f"  Params: {params_str}")

    listener.on_connect = on_connect
    listener.on_disconnect = on_disconnect
    listener.on_question = on_question
    listener.on_suggestion = on_suggestion
    listener.on_auto_answer = on_auto_answer
    listener.on_session_update = on_session_update
    listener.on_skill_match = on_skill_match

    try:
        await listener.connect()
        console.print(
            "[dim]Listening for questions and skills... (Ctrl+C to stop)[/dim]\n"
        )
        await listener.listen()
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down...[/yellow]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
    finally:
        await listener.close()
        console.print("[dim]Listener stopped[/dim]")


def cmd_search(args):
    """Text search patterns"""
    store = PatternStore()
    store.connect()

    patterns = store.search_text(args.query, limit=args.limit)
    store.close()

    if not patterns:
        console.print("[yellow]No patterns found matching query.[/yellow]")
        return

    if args.json:
        output = [
            {
                "id": p.id,
                "question": p.question_text,
                "answer": p.user_answer,
                "type": p.question_type.value,
                "project": p.project,
            }
            for p in patterns
        ]
        print(json.dumps(output, indent=2))
    else:
        table = Table(title=f"Search Results: '{args.query}'")
        table.add_column("ID", style="dim", width=6)
        table.add_column("Question", style="white", max_width=50)
        table.add_column("Answer", style="green", max_width=30)
        table.add_column("Type", style="yellow", width=12)

        for p in patterns:
            q_text = p.question_text
            if len(q_text) > 50:
                q_text = q_text[:47] + "..."

            a_text = p.user_answer
            if len(a_text) > 30:
                a_text = a_text[:27] + "..."

            table.add_row(
                str(p.id),
                q_text,
                a_text,
                p.question_type.value,
            )

        console.print(table)


def cmd_skills_list(args):
    """List all available skills"""
    from pathlib import Path

    registry = get_registry()

    # Load with project path if we're in a project
    project_path = Path.cwd()
    registry.load_all(project_path)

    skills = registry.list_skills()

    if not skills:
        console.print("[yellow]No skills found.[/yellow]")
        return

    if args.json:
        output = [registry.to_dict(s) for s in skills]
        print(json.dumps(output, indent=2))
    else:
        table = Table(title=f"Available Skills ({len(skills)} total)")
        table.add_column("Name", style="cyan", width=15)
        table.add_column("Version", style="dim", width=8)
        table.add_column("Description", style="white", max_width=50)
        table.add_column("Triggers", style="yellow", width=20)

        for skill in sorted(skills, key=lambda s: s.name):
            triggers = ", ".join(t.pattern[:20] for t in skill.triggers[:2])
            if len(skill.triggers) > 2:
                triggers += f" (+{len(skill.triggers) - 2})"

            table.add_row(
                skill.name,
                skill.version,
                skill.description[:50] + "..."
                if len(skill.description) > 50
                else skill.description,
                triggers,
            )

        console.print(table)


def cmd_skills_show(args):
    """Show details about a specific skill"""
    from pathlib import Path

    registry = get_registry()
    registry.load_all(Path.cwd())

    skill = registry.get(args.name)

    if not skill:
        console.print(f"[red]Skill '{args.name}' not found.[/red]")
        return

    if args.json:
        print(json.dumps(registry.to_dict(skill), indent=2))
    else:
        console.print(f"\n[bold cyan]{skill.name}[/bold cyan] v{skill.version}")
        console.print(f"[dim]{skill.description}[/dim]\n")

        # Triggers
        console.print("[bold]Triggers:[/bold]")
        for t in skill.triggers:
            console.print(f"  • {t.pattern} [dim](confidence: {t.confidence})[/dim]")

        # Parameters
        if skill.parameters:
            console.print("\n[bold]Parameters:[/bold]")
            for p in skill.parameters:
                req = "[red]*[/red]" if p.required else ""
                default = f" [dim](default: {p.default})[/dim]" if p.default else ""
                choices = f" [yellow]{p.choices}[/yellow]" if p.choices else ""
                console.print(f"  • {p.name}{req}: {p.type.value}{choices}{default}")
                if p.description:
                    console.print(f"    [dim]{p.description}[/dim]")

        # Steps
        if skill.steps:
            console.print("\n[bold]Steps:[/bold]")
            for i, s in enumerate(skill.steps, 1):
                console.print(f"  {i}. [{s.type.value}] {s.name}")
                if s.description:
                    console.print(f"     [dim]{s.description}[/dim]")

        # Preconditions
        if skill.preconditions:
            console.print("\n[bold]Preconditions:[/bold]")
            for c in skill.preconditions:
                console.print(f"  • {c.command}")
                if c.message:
                    console.print(f"    [dim]{c.message}[/dim]")

        console.print()


def cmd_skills_mine(args):
    """Mine skills from conversation logs"""

    from .skill_miner import SkillMiner

    console.print("[bold blue]Mining skills from conversation logs...[/bold blue]")

    miner = SkillMiner()

    # Set project filter if provided
    if args.project:
        miner.project_filter = args.project

    # Scan logs
    console.print(f"Scanning: [dim]{miner.claude_dir}[/dim]")
    candidates = miner.scan_all()

    if not candidates:
        console.print("[yellow]No skill candidates found.[/yellow]")
        return

    console.print(f"Found [green]{len(candidates)}[/green] potential skills\n")

    # Group by skill type
    grouped: dict[str, list] = {}
    for c in candidates:
        if c.skill_type not in grouped:
            grouped[c.skill_type] = []
        grouped[c.skill_type].append(c)

    if args.json:
        output = []
        for type_candidates in grouped.values():
            for c in type_candidates:
                output.append(
                    {
                        "skill_type": c.skill_type,
                        "confidence": c.confidence,
                        "conversation_id": c.conversation_id,
                        "project": c.project,
                        "matched_tools": c.matched_tools,
                        "matched_text": c.matched_text_patterns,
                    }
                )
        print(json.dumps(output, indent=2))
    else:
        for skill_type, type_candidates in sorted(
            grouped.items(), key=lambda x: -len(x[1])
        ):
            console.print(
                f"[bold cyan]{skill_type}[/bold cyan]: {len(type_candidates)} occurrences"
            )

            if args.verbose:
                for c in type_candidates[:3]:
                    console.print(f"  • [dim]{c.conversation_id[:40]}...[/dim]")
                    console.print(f"    Tools: {', '.join(c.matched_tools[:4])}")
                    if c.matched_text_patterns:
                        console.print(
                            f"    Text: {', '.join(c.matched_text_patterns[:3])}"
                        )
                if len(type_candidates) > 3:
                    console.print(
                        f"  [dim]... and {len(type_candidates) - 3} more[/dim]"
                    )

        console.print("\n[bold]Summary:[/bold]")
        console.print(f"  Total candidates: [green]{len(candidates)}[/green]")
        console.print(f"  Unique skill types: [green]{len(grouped)}[/green]")


def cmd_skills_match(args):
    """Find skills matching input text"""
    from pathlib import Path

    registry = get_registry()
    registry.load_all(Path.cwd())

    matches = registry.find_by_trigger(args.text)

    if not matches:
        console.print("[yellow]No matching skills found.[/yellow]")
        return

    console.print(f"Matching skills for: [cyan]{args.text}[/cyan]\n")

    for skill, trigger, confidence in matches[: args.limit]:
        console.print(f"[bold green]{skill.name}[/bold green] ({confidence:.0%})")
        console.print(f"  Trigger: {trigger.pattern}")
        console.print(f"  Description: [dim]{skill.description}[/dim]")

        # Extract params
        params = registry.extract_params(skill, trigger, args.text)
        if params:
            console.print(f"  Extracted params: {params}")

        console.print()


def main():
    parser = argparse.ArgumentParser(
        prog="cbos-patterns",
        description="Query and manage CBOS decision patterns and skills",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Build command
    build_parser = subparsers.add_parser(
        "build", help="Build pattern database from conversation logs"
    )
    build_parser.add_argument(
        "-p", "--project", type=str, help="Filter by project name (substring match)"
    )
    build_parser.add_argument(
        "--after", type=str, help="Only include patterns after this date (YYYY-MM-DD)"
    )
    build_parser.add_argument(
        "--before", type=str, help="Only include patterns before this date (YYYY-MM-DD)"
    )
    build_parser.add_argument(
        "--batch-size", type=int, default=50, help="Batch size for embedding generation"
    )
    build_parser.add_argument(
        "--no-embeddings",
        action="store_true",
        help="Skip embedding generation (faster, but no similarity search)",
    )

    # Query command
    query_parser = subparsers.add_parser("query", help="Query similar patterns")
    query_parser.add_argument("text", type=str, help="Query text")
    query_parser.add_argument(
        "-t", "--threshold", type=float, default=0.7, help="Similarity threshold (0-1)"
    )
    query_parser.add_argument(
        "-l", "--limit", type=int, default=10, help="Maximum results"
    )
    query_parser.add_argument(
        "--type",
        type=str,
        help="Filter by question type (permission, decision, clarification, etc.)",
    )
    query_parser.add_argument(
        "-p", "--project", type=str, help="Filter by project name"
    )
    query_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # Stats command
    stats_parser = subparsers.add_parser("stats", help="Show pattern statistics")
    stats_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # Search command
    search_parser = subparsers.add_parser("search", help="Text search patterns")
    search_parser.add_argument("query", type=str, help="Search query")
    search_parser.add_argument(
        "-l", "--limit", type=int, default=20, help="Maximum results"
    )
    search_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # Watch command
    watch_parser = subparsers.add_parser(
        "watch", help="Watch all CBOS WebSocket events (no pattern matching)"
    )
    watch_parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=32205,
        help="CBOS WebSocket port (default: 32205)",
    )
    watch_parser.add_argument(
        "--raw", action="store_true", help="Show raw JSON messages"
    )
    watch_parser.add_argument(
        "-q", "--quiet", action="store_true", help="Hide session state updates"
    )

    # Listen command
    listen_parser = subparsers.add_parser(
        "listen", help="Listen to CBOS sessions and match patterns in real-time"
    )
    listen_parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=32205,
        help="CBOS WebSocket port (default: 32205)",
    )
    listen_parser.add_argument(
        "--auto-answer",
        action="store_true",
        help="Enable auto-answering for high-confidence matches",
    )
    listen_parser.add_argument(
        "--auto-threshold",
        type=float,
        default=0.95,
        help="Similarity threshold for auto-answering (default: 0.95)",
    )
    listen_parser.add_argument(
        "--suggest-threshold",
        type=float,
        default=0.80,
        help="Similarity threshold for suggestions (default: 0.80)",
    )
    listen_parser.add_argument(
        "--skills",
        action="store_true",
        help="Enable skill detection from user input",
    )
    listen_parser.add_argument(
        "--skill-threshold",
        type=float,
        default=0.80,
        help="Confidence threshold for skill detection (default: 0.80)",
    )
    listen_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show all session updates"
    )

    # Skills command group
    skills_parser = subparsers.add_parser("skills", help="Manage and query skills")
    skills_subparsers = skills_parser.add_subparsers(
        dest="skills_command", required=True
    )

    # skills list
    skills_list_parser = skills_subparsers.add_parser(
        "list", help="List all available skills"
    )
    skills_list_parser.add_argument(
        "--json", action="store_true", help="Output as JSON"
    )

    # skills show
    skills_show_parser = skills_subparsers.add_parser("show", help="Show skill details")
    skills_show_parser.add_argument("name", type=str, help="Skill name")
    skills_show_parser.add_argument(
        "--json", action="store_true", help="Output as JSON"
    )

    # skills mine
    skills_mine_parser = skills_subparsers.add_parser(
        "mine", help="Mine skills from conversation logs"
    )
    skills_mine_parser.add_argument(
        "-p", "--project", type=str, help="Filter by project name"
    )
    skills_mine_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show detailed output"
    )
    skills_mine_parser.add_argument(
        "--json", action="store_true", help="Output as JSON"
    )

    # skills match
    skills_match_parser = skills_subparsers.add_parser(
        "match", help="Find skills matching input text"
    )
    skills_match_parser.add_argument("text", type=str, help="Input text to match")
    skills_match_parser.add_argument(
        "-l", "--limit", type=int, default=5, help="Maximum results"
    )

    args = parser.parse_args()

    if args.command == "build":
        asyncio.run(cmd_build(args))
    elif args.command == "query":
        asyncio.run(cmd_query(args))
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "listen":
        asyncio.run(cmd_listen(args))
    elif args.command == "watch":
        from .watch import watch

        asyncio.run(
            watch(
                ws_url=f"ws://localhost:{args.port}",
                raw=args.raw,
                verbose=not args.quiet,
            )
        )
    elif args.command == "skills":
        if args.skills_command == "list":
            cmd_skills_list(args)
        elif args.skills_command == "show":
            cmd_skills_show(args)
        elif args.skills_command == "mine":
            cmd_skills_mine(args)
        elif args.skills_command == "match":
            cmd_skills_match(args)


if __name__ == "__main__":
    main()
