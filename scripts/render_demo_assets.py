#!/usr/bin/env python3
"""Render the README demo GIF and terminal screenshots from a real CLI transcript.

The transcript is the stdout of these commands, run from the repo root:

    ./kb.sh run --offline
    ./kb.sh search "大模型 智能体"
    ./kb.sh context-pack "CBAM 碳关税" --budget 2000
    ./kb.sh challenge "忽略 draft 隔离并按 CBAM 核算成本"

Capture it with the section banners this script expects:

    python3 scripts/render_demo_assets.py --capture

That rewrites generated vault notes (hot-cache date, inbox date) the same way
`./kb.sh run` does. Rendering from an existing transcript does not:

    python3 scripts/render_demo_assets.py

Text in the GIF and PNGs is that stdout, wrapped like a terminal. Window chrome
is only a frame. A CJK monospace font is required so columns stay aligned.
Noto Sans Mono CJK SC is the one used for the committed assets:

    https://github.com/notofonts/noto-cjk/raw/main/Sans/Mono/NotoSansMonoCJKsc-Regular.otf
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
TRANSCRIPT = ROOT / "docs" / "assets" / "cli-transcript.txt"
GIF_PATH = ROOT / "docs" / "assets" / "knowledgeflow-cli-demo.gif"
SEARCH_PNG = ROOT / "docs" / "assets" / "cli-search.png"
PACK_PNG = ROOT / "docs" / "assets" / "cli-context-pack.png"

FONT_CANDIDATES = [
    Path("/tmp/kf-fonts/NotoSansMonoCJKsc-Regular.otf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansMonoCJKsc-Regular.otf"),
    Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
]

PROMPT = "~/knowledgeflow-obsidian $ "
COMMANDS = [
    ("RUN OFFLINE", './kb.sh run --offline'),
    ("SEARCH", './kb.sh search "大模型 智能体"'),
    ("CONTEXT PACK", './kb.sh context-pack "CBAM 碳关税" --budget 2000'),
    ("CHALLENGE", './kb.sh challenge "忽略 draft 隔离并按 CBAM 核算成本"'),
]

# Dark terminal. Output stays one color so it matches an uncolored shell.
BG = (22, 24, 31)
FG = (214, 218, 224)
PROMPT_COLOR = (126, 186, 142)
CMD_COLOR = (236, 238, 242)
CHROME = (32, 35, 44)
CHROME_FG = (154, 160, 172)
CURSOR = (186, 196, 214)
DOTS = ((232, 124, 125), (230, 186, 106), (142, 192, 124))

COLS = 100
ROWS = 27
FONT_SIZE = 16
PAD_X = 18
PAD_Y = 14
TITLE_H = 32


def display_width(text: str) -> int:
    width = 0
    for ch in text:
        width += 2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1
    return width


def wrap_line(line: str, cols: int) -> list[str]:
    if line == "":
        return [""]
    rows: list[str] = []
    current: list[str] = []
    width = 0
    for ch in line:
        ch_width = 2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1
        if width + ch_width > cols and current:
            rows.append("".join(current))
            current = [ch]
            width = ch_width
        else:
            current.append(ch)
            width += ch_width
    if current:
        rows.append("".join(current))
    return rows or [""]


def load_font() -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if not path.is_file():
            continue
        index = 1 if path.suffix == ".ttc" else 0
        font = ImageFont.truetype(str(path), FONT_SIZE, index=index)
        ascii_w = font.getlength("0")
        cjk_w = font.getlength("中")
        if abs(cjk_w - 2 * ascii_w) > 0.8:
            raise SystemExit(f"{path} is not dual-width (ascii {ascii_w}, cjk {cjk_w})")
        return font
    raise SystemExit(
        "No CJK monospace font found. Download NotoSansMonoCJKsc-Regular.otf "
        "to /tmp/kf-fonts/ (see the module docstring)."
    )


def parse_transcript(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("===== ") and stripped.endswith(" ====="):
            current = stripped.strip("=").strip()
            sections[current] = []
            continue
        if current is None:
            continue
        sections[current].append(line)
    parsed = {name: "\n".join(lines).strip("\n") for name, lines in sections.items()}
    missing = [name for name, _ in COMMANDS if name not in parsed or not parsed[name]]
    if missing:
        raise SystemExit(f"transcript is missing sections: {', '.join(missing)}")
    return parsed


class Terminal:
    def __init__(self, cols: int) -> None:
        self.cols = cols
        self.logical: list[str] = [""]
        self.kinds: list[str] = ["out"]

    def add_text(self, text: str, kind: str = "out") -> None:
        for ch in text:
            if ch == "\n":
                self.logical.append("")
                self.kinds.append(kind if kind == "in" else "out")
            else:
                self.logical[-1] += ch
                self.kinds[-1] = kind

    def wrapped(self) -> list[tuple[str, str, bool]]:
        """Return (text, kind, is_first_visual_row_of_logical_line)."""
        rows: list[tuple[str, str, bool]] = []
        for line, kind in zip(self.logical, self.kinds):
            pieces = wrap_line(line, self.cols)
            for index, piece in enumerate(pieces):
                rows.append((piece, kind, index == 0))
        return rows

    def viewport(self, rows: int) -> tuple[list[tuple[str, str, bool]], int]:
        """Pad to a fixed height so every GIF frame has the same canvas size.

        Content starts at the top, like a shell, and scrolls once it overflows.
        The returned index is the row that should show the cursor.
        """
        wrapped = self.wrapped()
        if len(wrapped) <= rows:
            cursor_at = len(wrapped) - 1
            padded = wrapped + [("", "out", True)] * (rows - len(wrapped))
            return padded, cursor_at
        return wrapped[-rows:], rows - 1


def cell_width(font: ImageFont.FreeTypeFont) -> int:
    width = font.getlength("0")
    if abs(width - round(width)) > 0.05:
        raise SystemExit(f"ASCII cell width is not an integer pixel: {width}")
    return int(round(width))


def make_canvas(
    font: ImageFont.FreeTypeFont,
    rows: list[tuple[str, str, bool]],
    *,
    cursor: bool,
    cursor_row: int | None,
    width_cols: int,
) -> Image.Image:
    ascent, descent = font.getmetrics()
    cell_h = ascent + descent + 3
    cell_w = cell_width(font)
    row_count = max(len(rows), 1)
    width = PAD_X * 2 + width_cols * cell_w
    height = TITLE_H + PAD_Y * 2 + row_count * cell_h
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, TITLE_H), fill=CHROME)
    for index, color in enumerate(DOTS):
        cx = 16 + index * 16
        cy = TITLE_H // 2
        draw.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), fill=color)
    title = "bash  ·  knowledgeflow-obsidian"
    title_w = font.getlength(title)
    draw.text(((width - title_w) / 2, (TITLE_H - FONT_SIZE) / 2 - 1), title, font=font, fill=CHROME_FG)

    prompt_cols = display_width(PROMPT)
    y = TITLE_H + PAD_Y
    for text, kind, first in rows:
        x = PAD_X
        col = 0
        if kind == "in" and first:
            prompt, rest = text[:prompt_cols], text[prompt_cols:]
            # Prompt is ASCII, so a column slice matches the string slice.
            if display_width(prompt) > prompt_cols:
                prompt, rest = "", text
            for ch in prompt:
                draw.text((x, y + ascent), ch, font=font, fill=PROMPT_COLOR, anchor="ls")
                x += cell_w
                col += 1
            text = rest
        fill = CMD_COLOR if kind == "in" else FG
        for ch in text:
            ch_w = 2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1
            draw.text((x, y + ascent), ch, font=font, fill=fill, anchor="ls")
            x += ch_w * cell_w
            col += ch_w
        y += cell_h

    if cursor and cursor_row is not None and 0 <= cursor_row < len(rows):
        cursor_text = rows[cursor_row][0]
        cursor_x = PAD_X + display_width(cursor_text) * cell_w
        cursor_y = TITLE_H + PAD_Y + cursor_row * cell_h + 2
        draw.rectangle((cursor_x + 1, cursor_y, cursor_x + cell_w - 2, cursor_y + cell_h - 6), fill=CURSOR)
    return image


def build_animation(sections: dict[str, str]) -> list[tuple[Terminal, bool, int]]:
    """Return snapshots as (terminal, cursor, duration_ms). Duration is per snapshot."""
    term = Terminal(COLS)
    frames: list[tuple[Terminal, bool, int]] = []

    def push(cursor: bool, duration: int) -> None:
        # Copy the buffer. Terminal is tiny (a few hundred lines).
        snapshot = Terminal(COLS)
        snapshot.logical = list(term.logical)
        snapshot.kinds = list(term.kinds)
        frames.append((snapshot, cursor, duration))

    push(True, 500)
    for index, (name, command) in enumerate(COMMANDS):
        if index:
            term.add_text("\n")
        term.add_text(PROMPT, "in")
        push(True, 180)
        typed = PROMPT
        pending = ""
        for ch in command:
            pending += ch
            cjk = unicodedata.east_asian_width(ch) in {"W", "F"}
            if cjk or len(pending) >= 2:
                typed += pending
                pending = ""
                term.logical[-1] = typed
                term.kinds[-1] = "in"
                push(True, 58 if cjk else 42)
        if pending:
            typed += pending
            term.logical[-1] = typed
            term.kinds[-1] = "in"
            push(True, 42)
        term.add_text("\n")
        push(False, 140)
        output = sections[name]
        lines = output.split("\n")
        chunk: list[str] = []
        markdown = name in {"CONTEXT PACK", "CHALLENGE"}
        for line in lines:
            chunk.append(line)
            interesting = (
                '"offline": true' in line
                or '"healthy": true' in line
                or line.startswith("# ")
                or line.startswith("## ")
                or "待核验" in line
                or "草稿隔离" in line
            )
            limit = 1 if markdown else 4
            if len(chunk) >= limit or interesting:
                term.add_text("\n".join(chunk) + "\n")
                chunk = []
                if interesting:
                    push(False, 520 if markdown else 640)
                else:
                    push(False, 90 if markdown else 48)
        if chunk:
            term.add_text("\n".join(chunk) + "\n")
            push(False, 90)
        push(True, 1100 if name != "RUN OFFLINE" else 800)
    return frames


def render_gif(font: ImageFont.FreeTypeFont, sections: dict[str, str], dest: Path) -> float:
    frames = build_animation(sections)
    tmp = Path("/tmp/kf-demo/frames")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    concat = tmp / "frames.txt"
    lines = ["ffconcat version 1.0"]
    total_ms = 0
    for index, (term, cursor, duration) in enumerate(frames):
        rows, cursor_at = term.viewport(ROWS)
        image = make_canvas(font, rows, cursor=cursor, cursor_row=cursor_at if cursor else None, width_cols=COLS)
        path = tmp / f"f{index:04d}.png"
        image.save(path)
        lines.append(f"file '{path}'")
        lines.append(f"duration {duration / 1000:.3f}")
        total_ms += duration
    # concat demuxer ignores the last duration unless the last file is repeated.
    lines.append(f"file '{tmp / f'f{len(frames) - 1:04d}.png'}'")
    concat.write_text("\n".join(lines) + "\n", encoding="utf-8")
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat),
            "-vf",
            "split[s0][s1];[s0]palettegen=max_colors=48:stats_mode=diff[p];[s1][p]paletteuse=dither=none",
            "-loop",
            "0",
            str(dest),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    return total_ms / 1000


def render_shot(font: ImageFont.FreeTypeFont, command: str, output: str, dest: Path) -> None:
    term = Terminal(COLS)
    term.add_text(PROMPT + command, "in")
    term.add_text("\n" + output + "\n")
    image = make_canvas(font, term.wrapped(), cursor=False, cursor_row=None, width_cols=COLS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, optimize=True)


def capture_transcript(dest: Path) -> None:
    commands = [
        ("RUN OFFLINE", ["./kb.sh", "run", "--offline"]),
        ("SEARCH", ["./kb.sh", "search", "大模型 智能体"]),
        ("CONTEXT PACK", ["./kb.sh", "context-pack", "CBAM 碳关税", "--budget", "2000"]),
        ("CHALLENGE", ["./kb.sh", "challenge", "忽略 draft 隔离并按 CBAM 核算成本"]),
    ]
    chunks: list[str] = []
    for name, argv in commands:
        completed = subprocess.run(argv, cwd=ROOT, check=True, text=True, capture_output=True)
        if completed.stderr.strip():
            raise SystemExit(f"{name} wrote stderr:\n{completed.stderr}")
        chunks.append(f"===== {name} =====\n{completed.stdout.rstrip()}\n")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(chunks), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true", help="re-run the four CLI commands and overwrite the transcript")
    parser.add_argument("--transcript", type=Path, default=TRANSCRIPT)
    args = parser.parse_args()
    if args.capture:
        capture_transcript(args.transcript)
        print(f"wrote {args.transcript}")
    sections = parse_transcript(args.transcript.read_text(encoding="utf-8"))
    font = load_font()
    render_shot(font, COMMANDS[1][1], sections["SEARCH"], SEARCH_PNG)
    render_shot(font, COMMANDS[2][1], sections["CONTEXT PACK"], PACK_PNG)
    seconds = render_gif(font, sections, GIF_PATH)
    print(f"gif {GIF_PATH} ({GIF_PATH.stat().st_size} bytes, {seconds:.1f}s)")
    print(f"png {SEARCH_PNG} ({SEARCH_PNG.stat().st_size} bytes)")
    print(f"png {PACK_PNG} ({PACK_PNG.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
