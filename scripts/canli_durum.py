"""Live scenarios' status: a table at the top of tasarim/plans/canli-test-senaryolari.md and a
mark on each scenario's heading, both from its "Sonuç kaydı" (a scenario's last row wins).
Run again after every live run; it rewrites what it wrote before.

    .venv\\Scripts\\python.exe scripts\\canli_durum.py
"""
import re
import sys
from pathlib import Path

FILE = Path(__file__).resolve().parent.parent / "tasarim" / "plans" / "canli-test-senaryolari.md"
MARKS = {"geçti": "✅", "kısmen": "◐", "kaldı": "❌", "atlandı": "⏭"}
NOT_RUN, NOT_BUILT = "⏳", "🚧"
NAMES = {"✅": "geçti", "◐": "kısmen", "❌": "kaldı", "⏭": "atlandı",
         NOT_RUN: "koşulmadı", NOT_BUILT: "dilim yok"}
# Slices not on main yet: their scenarios wait for them. Take one out when it merges.
UNBUILT = ("PLAN-82-", "PLAN-83-")
START = "<!-- durum: başla (scripts/canli_durum.py yazar) -->"
END = "<!-- durum: bitti -->"
HEADING = re.compile(
    r"^(#### ((?:DUMAN|CANLI|PLAN)-[A-Z0-9]+(?:-\d+)?) · )(.*?)(?: [✅◐❌⏭⏳🚧])?$", re.M)


def main() -> None:
    text = FILE.read_text(encoding="utf-8")
    last: dict[str, tuple[str, str, str]] = {}
    for row in text[text.index("## Sonuç kaydı"):].splitlines():
        cells = [c.strip() for c in row.split("|")]
        if len(cells) > 6 and re.match(r"(DUMAN|CANLI|PLAN)-", cells[3]):
            last[cells[3]] = (cells[5], cells[1], cells[2])  # result, date, commit

    def mark(sid: str) -> str:
        if sid in last:
            return MARKS.get(last[sid][0], NOT_RUN)
        return NOT_BUILT if sid.startswith(UNBUILT) else NOT_RUN

    found = HEADING.findall(text)
    text = HEADING.sub(lambda m: f"{m[1]}{m[3]} {mark(m[2])}", text)

    counts: dict[str, int] = {}
    rows = []
    for _, sid, title in found:
        m = mark(sid)
        counts[m] = counts.get(m, 0) + 1
        when = f"{last[sid][1]} {last[sid][2]}" if sid in last else ""
        rows.append(f"| {m} | {sid} | {title} | {when} |")
    summary = " · ".join(f"{m} {counts[m]} {NAMES[m]}" for m in NAMES if m in counts)
    table = "\n".join([
        START, "## Durum tablosu", "",
        f"{len(found)} senaryo: {summary}. Her senaryonun son sonucu; ayrıntısı en alttaki "
        "\"Sonuç kaydı\"nda.",
        "Başlıklardaki işaret aynıdır. Bir koşudan sonra `scripts/canli_durum.py` ile yeniden "
        "yazılır.", "",
        "| | Senaryo | Başlık | Son koşu |", "|---|---|---|---|", *rows, END])
    if START in text:
        text = text[:text.index(START)] + table + text[text.index(END) + len(END):]
    else:
        at = text.index("\n---\n\n## 1. ")
        text = text[:at] + "\n\n" + table + "\n" + text[at:]
    assert len(HEADING.findall(text)) == len(found)
    FILE.write_text(text, encoding="utf-8", newline="")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # (the console code page has no ✅)
    print(len(found), "scenarios:", summary)


if __name__ == "__main__":
    main()
