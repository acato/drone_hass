"""Entry point: python -m mavlink_mqtt_bridge --config path/to/bridge.yaml"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from pathlib import Path

from . import __version__, config, log
from .bridge import Bridge


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="mavlink_mqtt_bridge")
    p.add_argument(
        "--config",
        "-c",
        type=Path,
        default=Path("bridge.yaml"),
        help="Path to bridge.yaml (default: ./bridge.yaml)",
    )
    p.add_argument("--version", "-V", action="version", version=f"%(prog)s {__version__}")
    return p.parse_args(argv)


async def _run(cfg_path: Path) -> int:
    cfg = config.load(cfg_path)
    log.configure(level=cfg.logging.level, fmt=cfg.logging.format)
    logger = log.get_logger("main")
    logger.info("bridge.starting", version=__version__, config=str(cfg_path))

    bridge = Bridge(cfg)

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def _request_stop() -> None:
        logger.info("bridge.signal.stop")
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            # Windows: signal handlers via loop aren't available; KeyboardInterrupt is enough.
            pass

    run_task = asyncio.create_task(bridge.run(), name="bridge.run")
    stop_task = asyncio.create_task(stop.wait(), name="bridge.stop-wait")

    done, pending = await asyncio.wait(
        {run_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
    )

    for t in pending:
        t.cancel()
    for t in pending:
        try:
            await t
        except asyncio.CancelledError:
            pass

    # Surface exceptions from run_task if it failed.
    if run_task in done and run_task.exception() is not None:
        logger.error("bridge.failed", error=repr(run_task.exception()))
        return 1

    logger.info("bridge.stopped")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.config.exists():
        print(f"config not found: {args.config}", file=sys.stderr)
        return 2
    try:
        return asyncio.run(_run(args.config))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
