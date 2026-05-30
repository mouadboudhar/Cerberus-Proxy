import asyncio

import typer
from rich.console import Console
from rich.table import Table

from cerberus_proxy.auth.keys import generate_api_key, hash_key
from cerberus_proxy.auth.models import ApiKey
from cerberus_proxy.auth.repository import SQLiteKeyRepository
from cerberus_proxy.config.repository import SQLiteEndpointRepository
from cerberus_proxy.db import AsyncSessionLocal, init_db
from cerberus_proxy.ratelimit.bucket import TokenBucket, effective_limits

app = typer.Typer(help="Cerberus Proxy administration CLI.")
keys_app = typer.Typer(help="Manage Cerberus Proxy API keys.")
endpoints_app = typer.Typer(help="Manage Cerberus Proxy upstream endpoints.")
app.add_typer(keys_app, name="keys")
app.add_typer(endpoints_app, name="endpoints")

console = Console()


def _fmt(value) -> str:
    return value.isoformat(sep=" ", timespec="seconds") if value else "-"


async def _create_key(name: str) -> str:
    await init_db()
    plaintext = generate_api_key()
    async with AsyncSessionLocal() as session:
        repo = SQLiteKeyRepository(session)
        await repo.create(name=name, key_hash=hash_key(plaintext))
        await session.commit()
    return plaintext


async def _list_keys():
    await init_db()
    async with AsyncSessionLocal() as session:
        repo = SQLiteKeyRepository(session)
        return await repo.list_all()


async def _revoke_key(key_id: int) -> bool:
    await init_db()
    async with AsyncSessionLocal() as session:
        repo = SQLiteKeyRepository(session)
        ok = await repo.revoke(key_id)
        if ok:
            await session.commit()
        return ok


@keys_app.command("create")
def keys_create(
    name: str = typer.Option(..., "--name", help="Human-readable name for the key."),
) -> None:
    plaintext = asyncio.run(_create_key(name))
    console.print(
        f"[bold green]API Key created successfully.[/bold green]\n"
        f"Name: {name}\n"
        f"Key:  [bold]{plaintext}[/bold]\n\n"
        f"[yellow]SAVE THIS KEY — it will never be shown again.[/yellow]"
    )


@keys_app.command("list")
def keys_list() -> None:
    rows = asyncio.run(_list_keys())
    table = Table(title="Cerberus Proxy API Keys")
    table.add_column("ID", justify="right")
    table.add_column("Name")
    table.add_column("Created")
    table.add_column("Last Used")
    table.add_column("Status")
    for k in rows:
        status = "[green]Active[/green]" if k.is_active else "[red]Revoked[/red]"
        table.add_row(str(k.id), k.name, _fmt(k.created_at), _fmt(k.last_used_at), status)
    console.print(table)


@keys_app.command("revoke")
def keys_revoke(
    key_id: int = typer.Argument(..., help="ID of the key to revoke."),
) -> None:
    if not typer.confirm(f"Revoke key ID {key_id}?"):
        console.print("[yellow]Aborted.[/yellow]")
        raise typer.Exit(code=1)
    if asyncio.run(_revoke_key(key_id)):
        console.print(f"[green]Key ID {key_id} revoked.[/green]")
    else:
        console.print(f"[red]Key ID {key_id} not found or already revoked.[/red]")
        raise typer.Exit(code=1)


async def _set_key_limits(
    key_id: int,
    rpm: int | None,
    rph: int | None,
    rpd: int | None,
) -> tuple[ApiKey, dict[str, int], dict[str, int]] | None:
    await init_db()
    async with AsyncSessionLocal() as session:
        key = await session.get(ApiKey, key_id)
        if key is None:
            return None
        before = effective_limits(key)
        if rpm is not None:
            key.rate_limit_rpm = rpm
        if rph is not None:
            key.rate_limit_rph = rph
        if rpd is not None:
            key.rate_limit_rpd = rpd
        await session.commit()
        after = effective_limits(key)
        return key, before, after


async def _get_key_usage(key_id: int) -> tuple[ApiKey, dict[str, dict[str, int]]] | None:
    await init_db()
    async with AsyncSessionLocal() as session:
        key = await session.get(ApiKey, key_id)
        if key is None:
            return None
        usage = await TokenBucket().get_usage(session, key_id)
        return key, usage


def _fmt_resets(seconds: int) -> str:
    if seconds >= 3600:
        return f"{seconds // 3600}h"
    if seconds >= 60:
        return f"{seconds // 60}m"
    return f"{seconds}s"


@keys_app.command("set-limits")
def keys_set_limits(
    key_id: int = typer.Argument(..., help="ID of the key to update."),
    rpm: int | None = typer.Option(None, "--rpm", help="Requests per minute."),
    rph: int | None = typer.Option(None, "--rph", help="Requests per hour."),
    rpd: int | None = typer.Option(None, "--rpd", help="Requests per day."),
) -> None:
    if rpm is None and rph is None and rpd is None:
        console.print("[red]Pass at least one of --rpm, --rph, --rpd.[/red]")
        raise typer.Exit(code=1)
    result = asyncio.run(_set_key_limits(key_id, rpm, rph, rpd))
    if result is None:
        console.print(f"[red]Key ID {key_id} not found.[/red]")
        raise typer.Exit(code=1)
    key, before, after = result
    console.print(f"[bold]Key {key.id} — {key.name}[/bold]")
    console.print(
        f"  Minute: {before['minute']} -> {after['minute']}\n"
        f"  Hour:   {before['hour']} -> {after['hour']}\n"
        f"  Day:    {before['day']} -> {after['day']}"
    )


@keys_app.command("usage")
def keys_usage(
    key_id: int = typer.Argument(..., help="ID of the key to inspect."),
) -> None:
    result = asyncio.run(_get_key_usage(key_id))
    if result is None:
        console.print(f"[red]Key ID {key_id} not found.[/red]")
        raise typer.Exit(code=1)
    key, usage = result
    console.print(f"[bold]Key:[/bold] {key.name}")
    for window in ("minute", "hour", "day"):
        u = usage[window]
        console.print(
            f"  {window.capitalize():7s} {u['used']}/{u['limit']} used "
            f"(resets in {_fmt_resets(u['resets_in'])})"
        )


_VALID_PROVIDERS = {"openai", "anthropic", "ollama", "mistral"}


async def _create_endpoint(
    name: str, provider: str, upstream_url: str, default_model: str | None
):
    await init_db()
    async with AsyncSessionLocal() as session:
        repo = SQLiteEndpointRepository(session)
        endpoint = await repo.create(
            name=name,
            provider=provider,
            upstream_url=upstream_url,
            default_model=default_model,
        )
        await session.commit()
        return endpoint


async def _list_endpoints():
    await init_db()
    async with AsyncSessionLocal() as session:
        repo = SQLiteEndpointRepository(session)
        return await repo.list_all()


async def _delete_endpoint(endpoint_id: int) -> bool:
    await init_db()
    async with AsyncSessionLocal() as session:
        repo = SQLiteEndpointRepository(session)
        ok = await repo.delete(endpoint_id)
        if ok:
            await session.commit()
        return ok


@endpoints_app.command("create")
def endpoints_create(
    name: str = typer.Option(..., "--name", help="Human-readable name for the endpoint."),
    provider: str = typer.Option(
        ..., "--provider", help="Provider: openai/anthropic/ollama/mistral."
    ),
    upstream_url: str = typer.Option(
        ..., "--upstream-url", help="Base URL of the upstream provider."
    ),
    model: str | None = typer.Option(
        None, "--model", help="Optional default model for this endpoint."
    ),
) -> None:
    if provider.lower() not in _VALID_PROVIDERS:
        console.print(
            f"[red]Unknown provider '{provider}'.[/red] "
            f"Valid: {', '.join(sorted(_VALID_PROVIDERS))}"
        )
        raise typer.Exit(code=1)
    endpoint = asyncio.run(
        _create_endpoint(name, provider.lower(), upstream_url, model)
    )
    console.print(
        f"[bold green]Endpoint created.[/bold green]\n"
        f"ID:           {endpoint.id}\n"
        f"Name:         {endpoint.name}\n"
        f"Provider:     {endpoint.provider}\n"
        f"Upstream URL: {endpoint.upstream_url}\n"
        f"Model:        {endpoint.default_model or '-'}"
    )


@endpoints_app.command("list")
def endpoints_list() -> None:
    rows = asyncio.run(_list_endpoints())
    table = Table(title="Cerberus Proxy Endpoints")
    table.add_column("ID", justify="right")
    table.add_column("Name")
    table.add_column("Provider")
    table.add_column("Upstream URL")
    table.add_column("Model")
    table.add_column("Status")
    for e in rows:
        status = "[green]Active[/green]" if e.is_active else "[red]Inactive[/red]"
        table.add_row(
            str(e.id),
            e.name,
            e.provider,
            e.upstream_url,
            e.default_model or "-",
            status,
        )
    console.print(table)


@endpoints_app.command("delete")
def endpoints_delete(
    endpoint_id: int = typer.Argument(..., help="ID of the endpoint to delete."),
) -> None:
    if not typer.confirm(f"Delete endpoint ID {endpoint_id}?"):
        console.print("[yellow]Aborted.[/yellow]")
        raise typer.Exit(code=1)
    if asyncio.run(_delete_endpoint(endpoint_id)):
        console.print(f"[green]Endpoint ID {endpoint_id} deleted.[/green]")
    else:
        console.print(f"[red]Endpoint ID {endpoint_id} not found.[/red]")
        raise typer.Exit(code=1)
