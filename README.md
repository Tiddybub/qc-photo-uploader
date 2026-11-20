# qc-photo-uploader

A small command-line tool that sorts quality-control photos from a camera SD card into one folder per customer.

In the shop, every van kit is photographed before it ships. Each kit starts with a photo of a handwritten name page, followed by the photos of that kit. This tool takes the card, a short list of which photos are name pages, and copies everything into `<Customer Name> QC` folders, for example inside a Google Drive for desktop folder so the photos sync automatically.

## Features

- Splits the card at each name page: the name page and every photo after it belong to that customer until the next name page.
- Merges repeat customers: if a name shows up again later on the card (any capitalisation or spacing), those photos go into the same folder.
- Carries over the last customer from the previous card with `--carry-over NAME` for photos taken before the first name page.
- Copies, never moves. An existing file with different contents is never overwritten, and re-running after an interruption skips photos that are already copied.
- Verifies every card photo is in exactly one customer folder with a matching SHA-256 hash, then prints a per-customer count.
- Optional `--erase-card` sends the card photos to the Recycle Bin, only after a clean verification. Other files on the card are left alone.
- `--dry-run` shows the plan without changing anything.

## Requirements

- Python 3.8+
- Optional: [send2trash](https://pypi.org/project/Send2Trash/), only for `--erase-card`

```
pip install -r requirements.txt
```

## Usage

1. Look through the card and write a marks file with one line per name page: the photo's file name, a space, then the customer name.

   ```
   # marks.txt
   DSC05054.JPG Jane Doe
   DSC05081.JPG John Smith
   DSC05120.JPG Jane Doe
   ```

   Blank lines and lines starting with `#` are ignored.

2. Preview the plan:

   ```
   python qc_photo_uploader.py E:/DCIM/100MSDCF marks.txt "G:/My Drive/QC Photos" --dry-run
   ```

3. Copy and verify:

   ```
   python qc_photo_uploader.py E:/DCIM/100MSDCF marks.txt "G:/My Drive/QC Photos"
   ```

4. Copy, verify and clear the card in one go (photos before the first name page belong to the previous card's last customer here):

   ```
   python qc_photo_uploader.py E:/DCIM/100MSDCF marks.txt "G:/My Drive/QC Photos" --carry-over "John Smith" --erase-card
   ```

| Option | Description |
| --- | --- |
| `card` | Card photo folder holding `DSC*.JPG` files |
| `marks` | Marks file, one `<photo> <Customer Name>` line per name page |
| `dest` | Existing folder where the `<Customer Name> QC` folders are created |
| `--carry-over NAME` | Customer for photos before the first name page |
| `--dry-run` | Print the plan and change nothing |
| `--erase-card` | After verification passes, send the card photos to the Recycle Bin |

Exit codes: `0` success, `1` verification failed or no photos found, `2` bad input (missing folder, bad marks file, file conflict).

## Tests

```
python -m unittest
```

The tests build a fake card of small JPG files in a temporary folder and cover name-page boundaries, repeat-customer merging, carry-over, verification failures, `--erase-card` and `--dry-run`.

## Project structure

```
qc_photo_uploader.py       the tool (single module)
test_qc_photo_uploader.py  unit tests
requirements.txt           optional dependency for --erase-card
```

## Notes

- Photos are ordered by file name. If the camera's file counter rolls over from DSC09999 in the middle of a card, the order will be wrong for that card.
- Real marks files contain customer names, so `marks*.txt` is listed in `.gitignore`.
