"""Database CLI for utmelab-bank. Connect, query, inspect."""

from __future__ import annotations

import asyncio
import sys

import click

from utmelab_bank.config import load_settings
from utmelab_bank.adapters.database import bank_client


def run_async(coro):
    asyncio.run(coro)


@click.group()
def cli():
    """utmelab-bank database CLI."""
    pass


async def _status_impl():
    client = bank_client(load_settings())
    try:
        result = await client.execute(
            "SELECT state, COUNT(*) as cnt FROM staging_items GROUP BY state ORDER BY cnt DESC"
        )
        print("State breakdown:")
        for row in result.rows:
            print(f"  {row[0]}: {row[1]}")
        
        result = await client.execute(
            "SELECT exam, subject, state, COUNT(*) as cnt "
            "FROM staging_items GROUP BY exam, subject, state "
            "ORDER BY exam, subject, state"
        )
        print("\nBy exam/subject/state:")
        for row in result.rows:
            print(f"  {row[0]} / {row[1]} / {row[2]}: {row[3]}")
    finally:
        sys.exit(0)


@cli.command()
def status():
    """Show status summary."""
    asyncio.run(_do_status())


async def _do_status():
    client = bank_client(load_settings())
    try:
        result = await client.execute(
            "SELECT state, COUNT(*) as cnt FROM staging_items GROUP BY state ORDER BY cnt DESC"
        )
        print("State breakdown:")
        for row in result.rows:
            print(f"  {row[0]}: {row[1]}")
        
        result = await client.execute(
            "SELECT exam, subject, state, COUNT(*) as cnt "
            "FROM staging_items GROUP BY exam, subject, state "
            "ORDER BY exam, subject, state"
        )
        print("\nBy exam/subject/state:")
        for row in result.rows:
            print(f"  {row[0]} / {row[1]} / {row[2]}: {row[3]}")
    finally:
        sys.exit(0)


@cli.command()
def status():
    """Show status summary."""
    asyncio.run(_do_status())


@cli.command()
@click.option("--exam", default=None)
@click.option("--subject", default=None)
@click.option("--state", default=None)
@click.option("--limit", default=50, type=int)
def items(exam: str | None, subject: str | None, state: str | None, limit: int):
    async def _items():
        client = bank_client(load_settings())
        where_parts = []
        params = []
        if exam:
            where_parts.append("exam = ?")
            params.append(exam)
        if subject:
            where_parts.append("subject = ?")
            params.append(subject)
        if state:
            where_parts.append("state = ?")
            params.append(state)
        
        where_clause = "WHERE " + " AND ".join(where_parts) if where_parts else ""
        query = f"SELECT id, exam, subject, year, state, created_at FROM staging_items {where_clause} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        client = bank_client(load_settings())
        result = await client.execute(query, params)
        if not result.rows:
            print("(no items)")
            return
        col_widths = [len(c) for c in result.columns]
        for row in result.rows:
            for i, val in enumerate(row):
                col_widths[i] = max(col_widths[i], len(str(val)))
        
        header = " | ".join(c.ljust(w) for c, w in zip(result.columns, col_widths))
        sep = "-+-".join("-" * w for w in col_widths)
        print(header)
        print(sep)
        for row in result.rows:
            print(" | ".join(str(v).ljust(w) for v, w in zip(row, col_widths)))
        sys.exit(0)


@cli.command()
@click.option("--exam", default=None)
@click.option("--subject", default=None)
@click.option("--state", default=None)
@click.option("--limit", default=50, type=int)
def items(exam: str | None, subject: str | None, state: str | None, limit: int):
    async def _items():
        client = bank_client(load_settings())
        where_parts = []
        params = []
        if exam:
            where_parts.append("exam = ?")
            params.append(exam)
        if subject:
            where_parts.append("subject = ?")
            params.append(subject)
        if state:
            where_parts.append("state = ?")
            params.append(state)
        
        where_clause = "WHERE " + " AND ".join(where_parts) if where_parts else ""
        query = f"SELECT id, exam, subject, year, state, created_at FROM staging_items {where_clause} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        client = bank_client(load_settings())
        result = await client.execute(query, params)
        if not result.rows:
            print("(no items)")
            return
        col_widths = [len(c) for c in result.columns]
        for row in result.rows:
            for i, val in enumerate(row):
                col_widths[i] = max(col_widths[i], len(str(val)))
        
        header = " | ".join(c.ljust(w) for c, w in zip(result.columns, col_widths))
        sep = "-+-".join("-" * w for w in col_widths)
        print(header)
        print(sep)
        for row in result.rows:
            print(" | ".join(str(v).ljust(w) for v, w in zip(row, col_widths)))
        sys.exit(0)


@cli.command()
@click.argument("item_id")
def show(item_id: str):
    async def _show():
        client = bank_client(load_settings())
        try:
            result = await client.execute("SELECT * FROM staging_items WHERE id = ?", [item_id])
            if not result.rows:
                print(f"Item {item_id} not found")
                return
            row = result.rows[0]
            for col, val in zip(result.columns, row):
                print(f"{col}: {val}")
        finally:
            sys.exit(0)
    asyncio.run(_show())


@cli.command()
def exams():
    async def _exams():
        client = bank_client(load_settings())
        result = await client.execute("SELECT DISTINCT exam FROM staging_items ORDER BY exam")
        for row in result.rows:
            print(row[0])
        sys.exit(0)
    asyncio.run(_exams())


@cli.command()
@click.argument("exam")
def subjects_cmd(exam: str):
    async def _subjects():
        client = bank_client(load_settings())
        result = await client.execute(
            "SELECT DISTINCT subject FROM staging_items WHERE exam = ? ORDER BY subject", 
            [exam]
        )
        for row in result.rows:
            print(row[0])
        sys.exit(0)
    asyncio.run(_subjects())


@cli.command()
@click.argument("query")
def sql_cmd(query: str):
    async def _sql():
        client = bank_client(load_settings())
        try:
            result = await client.execute(query)
            if not result.rows:
                print("(no rows)")
                return
            col_widths = [len(c) for c in result.columns]
            for row in result.rows:
                for i, val in enumerate(row):
                    col_widths[i] = max(col_widths[i], len(str(val)))
            
            header = " | ".join(c.ljust(w) for c, w in zip(result.columns, col_widths))
            sep = "-+-".join("-" * w for w in col_widths)
            print(header)
            print(sep)
            for row in result.rows:
                print(" | ".join(str(v).ljust(w) for v, w in zip(row, col_widths)))
            print(f"\n({len(result.rows)} rows)")
        finally:
            sys.exit(0)
    asyncio.run(_sql())


@cli.command()
def exams_list():
    async def _exams():
        client = bank_client(load_settings())
        result = await client.execute("SELECT DISTINCT exam FROM staging_items ORDER BY exam")
        for row in result.rows:
            print(row[0])
        sys.exit(0)
    asyncio.run(_exams())


@cli.command()
@click.argument("exam")
def subjects_cmd(exam: str):
    async def _subjects():
        client = bank_client(load_settings())
        result = await client.execute(
            "SELECT DISTINCT subject FROM staging_items WHERE exam = ? ORDER BY subject", 
            [exam]
        )
        for row in result.rows:
            print(row[0])
        sys.exit(0)
    asyncio.run(_subjects())


@cli.command()
@click.argument("query")
def sql_cmd(query: str):
    async def _sql():
        client = bank_client(load_settings())
        try:
            result = await client.execute(query)
            if not result.rows:
                print("(no rows)")
                return
            col_widths = [len(c) for c in result.columns]
            for row in result.rows:
                for i, val in enumerate(row):
                    col_widths[i] = max(col_widths[i], len(str(val)))
            
            header = " | ".join(c.ljust(w) for c, w in zip(result.columns, col_widths))
            sep = "-+-".join("-" * w for w in col_widths)
            print(header)
            print(sep)
            for row in result.rows:
                print(" | ".join(str(v).ljust(w) for v, w in zip(row, col_widths)))
            print(f"\n({len(result.rows)} rows)")
        finally:
            sys.exit(0)
    asyncio.run(_sql())


@cli.command()
def status():
    async def _status():
        client = bank_client(load_settings())
        try:
            result = await client.execute(
                "SELECT state, COUNT(*) as cnt FROM staging_items GROUP BY state ORDER BY cnt DESC"
            )
            print("State breakdown:")
            for row in result.rows:
                print(f"  {row[0]}: {row[1]}")
            
            result = await client.execute(
                "SELECT exam, subject, state, COUNT(*) as cnt "
                "FROM staging_items GROUP BY exam, subject, state "
                "ORDER BY exam, subject, state"
            )
            print("\nBy exam/subject/state:")
            for row in result.rows:
                print(f"  {row[0]} / {row[1]} / {row[2]}: {row[3]}")
        finally:
            sys.exit(0)
    asyncio.run(_status())


@cli.command()
@click.option("--exam", default=None)
@click.option("--subject", default=None)
@click.option("--state", default=None)
@click.option("--limit", default=50, type=int)
def items(exam: str | None, subject: str | None, state: str | None, limit: int):
    async def _items():
        client = bank_client(load_settings())
        try:
            where_parts = []
            params = []
            if exam:
                where_parts.append("exam = ?")
                params.append(exam)
            if subject:
                where_parts.append("subject = ?")
                params.append(subject)
            if state:
                where_parts.append("state = ?")
                params.append(state)
            
            where_clause = "WHERE " + " AND ".join(where_parts) if where_parts else ""
            query = f"SELECT id, exam, subject, year, state, created_at FROM staging_items {where_clause} ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            
            client = bank_client(load_settings())
            result = await client.execute(query, params)
            if not result.rows:
                print("(no items)")
                return
            col_widths = [len(c) for c in result.columns]
            for row in result.rows:
                for i, val in enumerate(row):
                    col_widths[i] = max(col_widths[i], len(str(val)))
            
            header = " | ".join(c.ljust(w) for c, w in zip(result.columns, col_widths))
            sep = "-+-".join("-" * w for w in col_widths)
            print(header)
            print(sep)
            for row in result.rows:
                print(" | ".join(str(v).ljust(w) for v, w in zip(row, col_widths)))
        finally:
            sys.exit(0)
    asyncio.run(_items())


@cli.command()
@click.argument("item_id")
def show(item_id: str):
    async def _show():
        client = bank_client(load_settings())
        try:
            result = await client.execute("SELECT * FROM staging_items WHERE id = ?", [item_id])
            if not result.rows:
                print(f"Item {item_id} not found")
                return
            row = result.rows[0]
            for col, val in zip(result.columns, row):
                print(f"{col}: {val}")
        finally:
            sys.exit(0)
    asyncio.run(_show())


@cli.command()
def exams_list():
    async def _exams():
        client = bank_client(load_settings())
        try:
            result = await client.execute("SELECT DISTINCT exam FROM staging_items ORDER BY exam")
            for row in result.rows:
                print(row[0])
        finally:
            sys.exit(0)
    asyncio.run(_exams())


@cli.command()
@click.argument("exam")
def subjects_cmd(exam: str):
    async def _subjects():
        client = bank_client(load_settings())
        try:
            result = await client.execute(
                "SELECT DISTINCT subject FROM staging_items WHERE exam = ? ORDER BY subject", 
                [exam]
            )
            for row in result.rows:
                print(row[0])
        finally:
            sys.exit(0)
    asyncio.run(_subjects())


@cli.command()
@click.argument("query")
def sql_cmd(query: str):
    async def _sql():
        client = bank_client(load_settings())
        try:
            result = await client.execute(query)
            if not result.rows:
                print("(no rows)")
                return
            col_widths = [len(c) for c in result.columns]
            for row in result.rows:
                for i, val in enumerate(row):
                    col_widths[i] = max(col_widths[i], len(str(val)))
            
            header = " | ".join(c.ljust(w) for c, w in zip(result.columns, col_widths))
            sep = "-+-".join("-" * w for w in col_widths)
            print(header)
            print(sep)
            for row in result.rows:
                print(" | ".join(str(v).ljust(w) for v, w in zip(row, col_widths)))
            print(f"\n({len(result.rows)} rows)")
        finally:
            sys.exit(0)
    asyncio.run(_sql())


if __name__ == "__main__":
    cli()
