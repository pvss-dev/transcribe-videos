import argparse

from ..retention import RetentionPolicy
from .server import run

parser = argparse.ArgumentParser(
    prog="transcriptor-web",
    description="Start the Transcriptor web interface",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog="""
Automatic cleanup is off unless you set a limit:
  %(prog)s --retention-days 7
  %(prog)s --retention-max-gb 2 --retention-interval 30
""",
)
parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes")

cleanup = parser.add_argument_group("automatic cleanup (off unless a limit is set)")
cleanup.add_argument("--retention-days", type=float, metavar="N",
                     help="Delete transcripts older than N days")
cleanup.add_argument("--retention-keep", type=int, metavar="N",
                     help="Keep only the N newest transcripts")
cleanup.add_argument("--retention-max-gb", type=float, metavar="N",
                     help="Keep the output folder under N gigabytes")
cleanup.add_argument("--retention-interval", type=float, default=60.0, metavar="MIN",
                     help="Minutes between sweeps (default: 60)")

args = parser.parse_args()

policy = RetentionPolicy(
    max_age_days=args.retention_days,
    max_files=args.retention_keep,
    max_total_bytes=int(args.retention_max_gb * 1e9) if args.retention_max_gb else None,
    # Transcripts are the only output this service produces, so a cleanup that
    # skipped them would never delete anything at all.
    include_transcripts=True,
)

run(
    host=args.host,
    port=args.port,
    reload=args.reload,
    retention_policy=policy,
    retention_interval_minutes=args.retention_interval,
)
