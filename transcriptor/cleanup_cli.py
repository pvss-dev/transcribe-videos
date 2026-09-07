import argparse
import logging
import sys
from typing import Optional

from .retention import RetentionPolicy, sweep

logging.basicConfig(level=logging.WARNING, format="%(message)s")


def parse_arguments(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="transcriptor-clean",
        description="Delete old transcripts so the folder stops growing forever",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Nothing is deleted unless you set at least one limit, and --dry-run shows
exactly what would go before anything does.

Usage examples:
  %(prog)s --days 7 --dry-run        # see what a 7-day rule would remove
  %(prog)s --days 7                  # actually remove it
  %(prog)s --keep 200                # keep only the 200 newest transcripts
  %(prog)s --max-gb 1                # keep the folder under 1 GB

Run it from cron for an unattended server:
  0 4 * * *  /path/to/.venv/bin/transcriptor-clean --days 7 -o /srv/transcripts
        """,
    )

    parser.add_argument(
        "-o", "--output",
        default="./transcripts",
        help="Folder to clean (default: ./transcripts)",
    )
    parser.add_argument(
        "--days", type=float, metavar="N",
        help="Delete files last modified more than N days ago",
    )
    parser.add_argument(
        "--keep", type=int, metavar="N",
        help="Keep only the N newest files",
    )
    parser.add_argument(
        "--max-gb", type=float, metavar="N",
        help="Keep the folder under N gigabytes, deleting oldest first",
    )
    parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Show what would be deleted without deleting anything",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Only print the summary line",
    )

    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_arguments(argv)

    policy = RetentionPolicy(
        max_age_days=args.days,
        max_files=args.keep,
        max_total_bytes=int(args.max_gb * 1e9) if args.max_gb else None,
        # This project downloads nothing, so there are never .part files.
        max_partial_age_hours=None,
        # The output folder holds nothing but .txt/.srt, so excluding them
        # would turn every sweep into a silent no-op.
        include_transcripts=True,
    )

    # Refuse rather than sweep. Running the command to see what it does must
    # never cost the user a transcript.
    if not policy.is_active:
        print(
            "No limits given, so nothing was deleted.\n"
            "Set at least one of --days, --keep or --max-gb "
            "(add --dry-run to preview first).",
            file=sys.stderr,
        )
        return 2

    result = sweep(args.output, policy, dry_run=args.dry_run)

    if not args.quiet:
        for path in result.deleted:
            print(("would delete  " if args.dry_run else "deleted  ") + str(path))
        for problem in result.errors:
            print(f"failed: {problem}", file=sys.stderr)

    print(result.summary())
    if args.dry_run and result.deleted:
        print("\nNothing was removed. Re-run without --dry-run to apply.")

    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
