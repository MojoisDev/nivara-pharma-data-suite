"""Render a captioned walkthrough from real browser captures; requires ffmpeg/ffprobe."""

import json
import subprocess
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCENES = [
    (
        "01-sales.jpg",
        20,
        "01 / THE PROJECT",
        (
            "Nivara connects synthetic pharmaceutical sales, inventory, d"
            "ata quality, and reporting. Python and PostgreSQL power 24 m"
            "onths of data across four Indian regions and 120 medicines."
        ),
    ),
    (
        "02-inventory.jpg",
        18,
        "02 / INVENTORY CORRECTNESS",
        (
            "Stock is reconstructed from receipts less historical sales. "
            "Expiry exposure uses the reporting date; values are acquisit"
            "ion cost. Separate batch facts prevent sale lines from multi"
            "plying stock."
        ),
    ),
    (
        "03-quality-clean.jpg",
        12,
        "03 / THE CLEAN BASELINE",
        (
            "Thirty-three versioned rules cover six quality dimensions. T"
            "he clean synthetic demo scores 100 percent under its declare"
            "d historical replay clock."
        ),
    ),
    (
        "04-quality-corrupted.jpg",
        18,
        "04 / DELIBERATE SOURCE FAILURES",
        (
            "The corrupted demo detects 19 findings across 13 failing rec"
            "ords. Its 83.33 percent score weights quality dimensions; it"
            " is not simply a percentage of clean rows."
        ),
    ),
    (
        "05-quality-ledger.jpg",
        17,
        "05 / TRACEABLE REVIEW",
        (
            "The ledger retains source references, rule identifiers, seve"
            "rity, and issue status. Corrections require reviewer notes a"
            "nd revision checks. Status changes never silently repair sou"
            "rce data."
        ),
    ),
    (
        "06-workflows.jpg",
        20,
        "06 / ONE DEDICATED SCHEDULER",
        (
            "A dedicated scheduler chains validation, analytics, reportin"
            "g, alerts, and email preparation. PostgreSQL locks and reque"
            "st keys prevent overlapping controllers and duplicate reques"
            "ts. Attempts and outcomes are persisted."
        ),
    ),
    (
        "07-alerts.jpg",
        15,
        "07 / ACTIONABLE CONDITIONS",
        (
            "Alerts track stock, expiry, critical quality findings, and w"
            "orkflow failures. Reviewers can acknowledge conditions; reso"
            "lved and changed conditions retain audit history. Unchanged "
            "revisions do not create repeated notification summaries."
        ),
    ),
    (
        "08-reports.jpg",
        16,
        "08 / REPORT EVIDENCE",
        (
            "The seven-sheet annual workbook was checked against independ"
            "ent PostgreSQL totals: INR 54,539,450.97 revenue and INR 70,"
            "823,412.56 closing stock value. Downloads verify registered "
            "file checksums."
        ),
    ),
    (
        "09-mail.jpg",
        14,
        "09 / VERIFIED SCOPE",
        (
            "Email stays in local preview mode. The latest full suite pas"
            "sed all 92 tests, including PostgreSQL integration tests. Th"
            "is is a synthetic portfolio demonstration, not validated cli"
            "nical or regulatory software."
        ),
    ),
]


def clock(seconds):
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}.00"


def main():
    assert sum(scene[1] for scene in SCENES) == 150
    for filename, *_ in SCENES:
        assert (ROOT / "demo-captures" / filename).is_file(), filename
    with tempfile.TemporaryDirectory(prefix="nivara-demo-") as temporary:
        work = Path(temporary)
        entries = []
        subtitles = [
            "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\n",
            (
                "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour"
                ", SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
                "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, Border"
                "Style, Outline, Shadow, Alignment, MarginL, MarginR, MarginV"
                ", Encoding\n"
            ),
            (
                "Style: Caption,DejaVu Sans,32,&H00F5F5ED,&H00FFFFFF,&H001F37"
                "14,&H001F3714,0,0,0,0,100,100,0,0,1,0,0,2,60,60,24,1\n"
            ),
            (
                "Style: Title,DejaVu Sans,24,&H00A6C7A0,&H00FFFFFF,&H001F3714"
                ",&H001F3714,0,0,0,0,100,100,0,0,1,0,0,7,60,60,922,1\n"
            ),
            (
                "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, Ma"
                "rginR, MarginV, Effect, Text\n"
            ),
        ]
        elapsed = 0
        for filename, duration, title, caption in SCENES:
            path = ROOT / "demo-captures" / filename
            quoted = str(path).replace("'", "'\\''")
            entries += [f"file '{quoted}'", f"duration {duration}"]
            for style, content in [
                ("Title", title),
                ("Caption", r"\N".join(textwrap.wrap(caption, 90))),
            ]:
                subtitles.append(
                    f"Dialogue: 0,{clock(elapsed)},{clock(elapsed + duration)},{style},"
                    f",0,0,0,,{content}\n"
                )
            elapsed += duration
        entries.append(entries[-2])
        playlist = work / "scenes.txt"
        playlist.write_text("\n".join(entries) + "\n")
        captions = work / "captions.ass"
        captions.write_text("".join(subtitles))
        output = ROOT / "nivara-demo.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(playlist),
                "-vf",
                f"scale=1920:1080,drawbox=x=0:y=900:w=iw:h=180:color=0x14372f@0.96:t=fill,subtitles={captions}",
                "-t",
                "150",
                "-r",
                "12",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(output),
            ],
            check=True,
        )
    info = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(output),
            ]
        )
    )
    assert abs(float(info["format"]["duration"]) - 150) < 0.2
    stream = info["streams"][0]
    assert (stream["codec_name"], stream["width"], stream["height"]) == ("h264", 1920, 1080)
    evidence = {
        "duration_seconds": float(info["format"]["duration"]),
        "codec": stream["codec_name"],
        "resolution": "1920x1080",
        "audio": False,
        ("source"): (
            "Nine actual local dashboard captures, captioned and held for"
            " walkthrough pacing; not continuous screen recording"
        ),
        "bytes": output.stat().st_size,
    }
    (ROOT / "demo_metadata.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()
