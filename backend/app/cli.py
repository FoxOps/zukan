"""Admin command line.

zukan create-admin USERNAME
zukan sync GAME [--kind catalog|prices|images]
zukan import-images GAME FOLDER
"""

import argparse
import asyncio
import getpass
import logging
import os
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.core.security import end_all_sessions, hash_password
from app.games.base import get_provider
from app.main import register_games
from app.models import JobKind, Role, User
from app.services import images, jobs


async def create_admin(username: str, password: str) -> None:
    async with get_sessionmaker()() as session:
        user = await session.scalar(select(User).where(User.username == username))
        if user is None:
            user = User(username=username)
            session.add(user)
        else:
            # A reset password ends the account's sessions.
            await end_all_sessions(session, user)
        user.role = Role.admin
        user.disabled = False
        user.password_hash = hash_password(password)
        await session.commit()
    print(f"Administrator {username!r} ready")


async def sync(game_id: str, kind: JobKind) -> None:
    jobs.set_process_role("cli")
    await register_games()
    run_id = await jobs.run_job(game_id, kind)
    print(f"{kind} sync for {game_id} done (run {run_id})")


async def import_images(game_id: str, folder: Path) -> None:
    async with get_sessionmaker()() as session:
        report = await images.import_image_folder(session, get_provider(game_id), folder)
    print(f"{report.stored} images imported, {report.missing} printings without image")


def main() -> None:
    parser = argparse.ArgumentParser(prog="zukan")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("create-admin", help="create or reset an administrator")
    admin.add_argument("username")
    sync_cmd = commands.add_parser("sync", help="run a catalog, price or image job now")
    sync_cmd.add_argument("game")
    sync_cmd.add_argument("--kind", type=JobKind, default=JobKind.catalog, choices=list(JobKind))
    import_cmd = commands.add_parser("import-images", help="import card images from a folder")
    import_cmd.add_argument("game")
    import_cmd.add_argument("folder", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    if args.command == "create-admin":
        # Env var allows non-interactive bootstrap (docker compose run).
        password = os.environ.get("TCG_ADMIN_PASSWORD") or getpass.getpass("Password: ")
        if len(password) < 8:
            sys.exit("Password must be at least 8 characters")
        asyncio.run(create_admin(args.username, password))
    elif args.command == "sync":
        asyncio.run(sync(args.game, args.kind))
    elif args.command == "import-images":
        asyncio.run(import_images(args.game, args.folder))


if __name__ == "__main__":
    main()
