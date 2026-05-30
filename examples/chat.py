#!/usr/bin/env python3
"""Minimal REPL chat client for manually exercising the Cerberus Proxy proxy.

Usage:
    python examples/chat.py <cerberus_proxy_key> <provider_api_key>

Env overrides:
    CERBERUS_URL    base URL of the proxy (default: http://localhost:8000)
    CERBERUS_MODEL  model name sent in the request (default: gpt-4o-mini)

Commands inside the REPL:
    /reset    clear conversation history
    /history  print conversation so far
    /quit     exit (Ctrl-D / Ctrl-C also work)
"""
from __future__ import annotations

import os
import sys

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.text import Text
from rich.live import Live

console = Console()


def _usage_and_exit() -> None:
    console.print(__doc__, style="dim")
    sys.exit(2)


def main() -> int:
    if len(sys.argv) != 3:
        _usage_and_exit()

    cerberus_proxy_key = sys.argv[1]
    provider_key = sys.argv[2]
    base_url = os.environ.get("CERBERUS_URL", "http://localhost:8000").rstrip("/")
    model = os.environ.get("CERBERUS_MODEL", "gpt-4o-mini")
    url = f"{base_url}/v1/chat/completions"

    headers = {
        "X-Cerberus-Key": cerberus_proxy_key,
        "Authorization": f"Bearer {provider_key}",
        "Content-Type": "application/json",
    }

    history: list[dict[str, str]] = []
    
    console.rule("[bold blue]Cerberus Proxy Chat[/bold blue]")
    console.print(f"[dim]URL:[/dim] [cyan]{url}[/cyan] [dim]Model:[/dim] [green]{model}[/green]")
    console.print("Commands: [bold]/reset[/bold], [bold]/history[/bold], [bold]/quit[/bold]\n")

    with httpx.Client(timeout=60.0) as client:
        while True:
            try:
                user_input = console.input("[bold magenta]you>[/bold magenta] ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[yellow]Goodbye![/yellow]")
                return 0

            if not user_input:
                continue
            if user_input in {"/quit", "/exit"}:
                console.print("[yellow]Goodbye![/yellow]")
                return 0
            if user_input == "/reset":
                history.clear()
                console.print("[bold yellow](history cleared)[/bold yellow]\n")
                continue
            if user_input == "/history":
                console.print(Panel(
                    "\n".join([f"[bold]{m['role']}:[/bold] {m['content']}" for m in history]),
                    title="Conversation History",
                    border_style="blue"
                ))
                continue

            history.append({"role": "user", "content": user_input})
            payload = {"model": model, "messages": history}

            try:
                with console.status("[bold green]Thinking..."):
                    response = client.post(url, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                history.pop()
                console.print(f"[bold red][network error][/bold red] {exc}\n")
                continue

            if response.status_code == 403:
                history.pop()
                try:
                    body = response.json()
                except ValueError:
                    console.print(f"[bold red][403][/bold red] {response.text}\n")
                    continue
                if body.get("error") == "blocked_by_guard":
                    console.print(Panel(
                        f"[bold red]BLOCKED by {body.get('guard')}[/bold red]\n"
                        f"[bold]Reason:[/bold] {body.get('reason_code')} ({body.get('severity')})\n"
                        f"[bold]Detail:[/bold] {body.get('detail')}",
                        border_style="red",
                        title="Guard Action"
                    ))
                else:
                    console.print(f"[bold red][403][/bold red] {body}\n")
                continue

            if response.status_code >= 400:
                history.pop()
                console.print(f"[bold red][{response.status_code}][/bold red] {response.text}\n")
                continue

            try:
                data = response.json()
                reply = data["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError) as exc:
                history.pop()
                console.print(f"[bold red][bad response shape: {exc}][/bold red] {response.text}\n")
                continue

            history.append({"role": "assistant", "content": reply})
            console.print(Panel(Markdown(reply), title="[bold green]bot[/bold green]", border_style="green"))
            console.print()


if __name__ == "__main__":
    raise SystemExit(main())
