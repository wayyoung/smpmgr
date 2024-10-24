"""The image subcommand group."""

import asyncio
import logging
from io import BufferedReader
from pathlib import Path
from typing import cast

import typer
from rich import print
from rich.progress import (BarColumn, DownloadColumn, Progress, TextColumn,
                           TimeRemainingColumn, TransferSpeedColumn)
from smp.exceptions import SMPBadStartDelimiter
from smpclient import SMPClient
from smpclient.generics import error, success
from smpclient.mcuboot import ImageInfo
from smpclient.requests.image_management import ImageStatesRead
from smpclient.requests.mgmt_ex import MgmtExStatesRead
from typing_extensions import Annotated

from smpmgr.common import (Options, connect_with_spinner, get_smpclient,
                           smp_request)

app = typer.Typer(name="image", help="The SMP Image Management Group.")
logger = logging.getLogger(__name__)


@app.command()
def state_read(ctx: typer.Context) -> None:
    """Request to read the state of FW images on the SMP Server."""

    options = cast(Options, ctx.obj)
    smpclient = get_smpclient(options)

    async def f() -> None:
        await connect_with_spinner(smpclient)

        r = await smp_request(smpclient, options, MgmtExStatesRead(), "Waiting for image states...")  # type: ignore # noqa

        if error(r):
            print(r)
        elif success(r):
            if len(r.images) == 0:
                print("No images on device!")
            for image in r.images:
                print(image)
            if r.splitStatus is not None:
                print(f"splitStatus: {r.splitStatus}")
        else:
            raise Exception("Unreachable")

    asyncio.run(f())


async def download_with_progress_bar(
    smpclient: SMPClient, file: typer.FileBinaryRead | BufferedReader, slot: int = 0
) -> None:
    """Animate a progress bar while downloading the FW image."""

    with Progress(
        TextColumn("[bold blue]{task.fields[filename]}", justify="right"),
        BarColumn(),
        "[progress.percentage]{task.percentage:>3.1f}%",
        "•",
        DownloadColumn(),
        "•",
        TransferSpeedColumn(),
        "•",
        TimeRemainingColumn(),
    ) as progress:
        image = file.read()
        file.close()
        task = progress.add_task("Downloading", total=len(image), filename=file.name, start=True)
        try:
            async for offset in smpclient.upload(image, slot):
                progress.update(task, completed=offset)
                logger.info(f"Download {offset=}")
        except SMPBadStartDelimiter as e:
            progress.stop()
            logger.info(f"Bad start delimiter: {e}")
            logger.error("Got an unexpected response, is the device an SMP server?")
            raise typer.Exit(code=1)
        except OSError as e:
            logger.error(f"Connection to device lost: {e.__class__.__name__} - {e}")
            raise typer.Exit(code=1)


@app.command()
def download(
    ctx: typer.Context,
    file: Annotated[Path, typer.Argument(help="Path to FW image")],
    slot: Annotated[int, typer.Option(help="The image slot to download to")] = 0,
) -> None:
    """Download a FW image."""

    try:
        image_info = ImageInfo.load_file(str(file))
        logger.info(str(image_info))
    except Exception:
        logger.exception("Inspection of FW image failed")
        raise typer.Exit(code=1)

    smpclient = get_smpclient(cast(Options, ctx.obj))

    async def f() -> None:
        await connect_with_spinner(smpclient)
        with open(file, "rb") as f:
            await download_with_progress_bar(smpclient, f, slot)

    asyncio.run(f())
