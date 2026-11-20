#!/usr/bin/env python3
"""Sort QC photos from a camera card into one folder per customer.

Each kit on the card starts with a photo of a handwritten name page. Every
photo from a name page up to the next one belongs to that customer. The name
pages are listed in a marks file, one per line:

    DSC05054.JPG Jane Doe

Photos are copied (never moved) into "<dest>/<Customer Name> QC/" and checked
by SHA-256 before the card can be cleared.
"""

import argparse
import fnmatch
import hashlib
import shutil
import sys
from collections import Counter
from pathlib import Path

PHOTO_PATTERN = "DSC*.JPG"
INVALID_NAME_CHARS = set('<>:"/\\|?*')


def list_photos(card_dir):
    """Return the card's photos sorted by file name."""
    # Sorted by name: a counter that wraps past DSC09999 mid-card would misorder; sort by capture time if that happens.
    photos = [p for p in Path(card_dir).iterdir()
              if p.is_file() and fnmatch.fnmatchcase(p.name.upper(), PHOTO_PATTERN)]
    return sorted(photos, key=lambda p: p.name.upper())


def clean_name(name):
    """Collapse whitespace and reject names that cannot be a folder name."""
    name = " ".join(name.split())
    bad = INVALID_NAME_CHARS.intersection(name)
    if not name or bad:
        raise ValueError(f"customer name {name!r} is empty or has characters not allowed in a folder name: {''.join(sorted(bad))}")
    return name


def read_marks(marks_file):
    """Return {PHOTO NAME (upper case): customer name} from the marks file."""
    marks = {}
    lines = Path(marks_file).read_text(encoding="utf-8-sig").splitlines()
    for number, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        if len(parts) < 2:
            raise ValueError(f"marks line {number}: expected '<photo> <Customer Name>', got {line!r}")
        photo = parts[0].upper()
        if photo in marks:
            raise ValueError(f"marks line {number}: {parts[0]} is marked twice")
        marks[photo] = clean_name(parts[1])
    return marks


def build_plan(photos, marks, carry_over=None):
    """Return [(photo path, customer name)] in card order."""
    missing = sorted(set(marks) - {p.name.upper() for p in photos})
    if missing:
        raise ValueError("marked photos are not on the card: " + ", ".join(missing))
    spelling = {}  # casefolded name -> first spelling, so a repeat customer merges into one folder
    current = clean_name(carry_over) if carry_over else None
    plan = []
    for photo in photos:
        current = marks.get(photo.name.upper(), current)
        if current is None:
            raise ValueError(f"{photo.name} comes before the first name page; pass --carry-over NAME")
        current = spelling.setdefault(current.casefold(), current)
        plan.append((photo, current))
    return plan


def folder_for(dest, customer):
    return Path(dest) / f"{customer} QC"


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_photos(plan, dest):
    """Copy each photo into its customer folder; never overwrite a different file."""
    for photo, customer in plan:
        target = folder_for(dest, customer) / photo.name
        if target.exists():
            if sha256(target) == sha256(photo):
                continue  # already copied by an earlier run
            raise FileExistsError(f"{target} already exists with different contents; not overwriting it")
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(photo, target)


def verify(plan, dest):
    """Return a list of problems; empty means every photo is intact in exactly one folder."""
    folders = {folder_for(dest, customer) for _, customer in plan}
    problems = []
    for photo, customer in plan:
        expected = folder_for(dest, customer)
        found = sorted(f.name for f in folders if (f / photo.name).exists())
        if found != [expected.name]:
            problems.append(f"{photo.name}: expected only in '{expected.name}', found in {found or 'no folder'}")
        elif sha256(expected / photo.name) != sha256(photo):
            problems.append(f"{photo.name}: copy in '{expected.name}' does not match the card")
    return problems


def print_summary(plan):
    for customer, count in Counter(customer for _, customer in plan).items():
        print(f"  {customer} QC: {count} photo(s)")
    print(f"  Total: {len(plan)} photo(s)")


def load_send2trash():
    """Return send2trash's function, or None when the package is not installed."""
    try:
        from send2trash import send2trash
    except ImportError:
        return None
    return send2trash


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Copy QC photos from a camera card into one folder per customer.")
    parser.add_argument("card", help="card photo folder, e.g. E:/DCIM/100MSDCF")
    parser.add_argument("marks", help="marks file: one '<photo> <Customer Name>' line per name page")
    parser.add_argument("dest", help="existing folder that holds the '<Customer Name> QC' folders")
    parser.add_argument("--carry-over", metavar="NAME", help="customer for photos before the first name page")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and change nothing")
    parser.add_argument("--erase-card", action="store_true",
                        help="after a clean verification, send the card photos to the Recycle Bin")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    trash = None
    if args.erase_card and not args.dry_run:
        trash = load_send2trash()
        if trash is None:
            print("error: --erase-card needs the send2trash package (pip install send2trash). Nothing was copied.",
                  file=sys.stderr)
            return 2
    if not Path(args.dest).is_dir():
        print(f"error: destination folder {args.dest} does not exist", file=sys.stderr)
        return 2
    try:
        plan = build_plan(list_photos(args.card), read_marks(args.marks), args.carry_over)
    except (OSError, ValueError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    if not plan:
        print(f"No {PHOTO_PATTERN} photos found in {args.card}.")
        return 1

    if args.dry_run:
        for photo, customer in plan:
            print(f"{photo.name} -> {folder_for(args.dest, customer)}")
        print("Dry run, nothing copied:")
        print_summary(plan)
        if args.erase_card:
            print(f"Would send {len(plan)} card photo(s) to the Recycle Bin after verification.")
        return 0

    try:
        copy_photos(plan, args.dest)
    except OSError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    print("Copied:")
    print_summary(plan)

    problems = verify(plan, args.dest)
    if problems:
        print("Verification FAILED; the card was not touched:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"Verified: all {len(plan)} photo(s) match the card (SHA-256).")

    if trash:
        for photo, _ in plan:  # only the verified photos, never other files on the card
            trash(str(photo))
        print(f"Sent {len(plan)} card photo(s) to the Recycle Bin.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
