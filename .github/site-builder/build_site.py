#!/usr/bin/env python3
"""
Builds a student's game-manual website from manual.md, topics/, images/,
and design.md, using DITA-OT (run in Docker).

Steps:
  1. Copy the student's files into _build/src (their files are never changed).
  2. Check the map and topics, fixing small mistakes in the copy and
     collecting plain-English problems for anything that can't be fixed.
  3. Turn design.md into a stylesheet.
  4. Run DITA-OT to make HTML5.
  5. Add the banner, footer, fonts, and stylesheet to every page.
  6. Write a report (Actions summary + _build/report.md for the issue).

Run locally from the repo root with:  python3 .github/site-builder/build_site.py
"""

import datetime
import difflib
import html
import html.parser
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
WORK = REPO / "_build"
SRC = WORK / "src"
OUT = REPO / "_site"
DITA_IMAGE = os.environ.get("DITA_IMAGE", "ghcr.io/dita-ot/dita-ot:4.4.1")

SKIP_DIRS = {".git", ".github", "_build", "_site", "node_modules", ".vscode"}
TOPIC_TYPES = ("concept", "task", "reference")
CODE_IN_STEPS = []  # task topics with a code block indented under a step
MAP_SCHEMA = "---\n$schema: urn:oasis:names:tc:dita:xsd:map.xsd\n---\n"


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

class Report:
    def __init__(self):
        self.errors = []    # site can't be built until these are fixed
        self.warnings = []  # site builds, but something looks wrong
        self.fixes = []     # small mistakes the builder fixed in its copy
        self.design = []    # (setting, value used, note)
        self.moved = []     # links to files found in a different folder
        self.pages = []     # (menu label, file, topic type) in menu order
        self.dita_log = ""

    def error(self, msg): self.errors.append(msg)
    def warn(self, msg): self.warnings.append(msg)
    def fixed(self, msg): self.fixes.append(msg)


R = Report()


def site_url():
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        return None
    owner, name = repo.split("/", 1)
    return f"https://{owner.lower()}.github.io/{name}/"


def write_report(success):
    lines = []
    url = site_url()
    if success:
        lines.append("## ✅ Your website was updated")
        if url:
            lines.append(f"\nSee it here: **{url}** (it can take a minute to appear, "
                         "and you may need to refresh the page).")
    else:
        lines.append("## ❌ Your website was NOT updated")
        lines.append("\nThe builder found a problem it couldn't fix. Your old website is still "
                     "online. Fix the problems below, commit again, and the site will update.")

    def section(title, items):
        if items:
            lines.append(f"\n### {title}\n")
            lines.extend(f"- {i}" for i in items)

    section("Problems you need to fix", R.errors)
    section("Things to check", R.warnings)
    section("Small mistakes the builder fixed for you", R.fixes)
    if R.fixes:
        lines.append("\n_Your files were not changed. The builder fixed these in its own copy, "
                     "so you can fix them in your files whenever you like._")

    if R.design:
        lines.append("\n### Design settings used\n")
        lines.append("| Setting | Used | Note |")
        lines.append("|---|---|---|")
        for name, value, note in R.design:
            lines.append(f"| {name} | {value} | {note} |")

    if R.dita_log and not success:
        lines.append("\n<details><summary>Technical details (share these with your instructor "
                     "if you're stuck)</summary>\n\n```")
        lines.append(R.dita_log.strip()[-6000:])
        lines.append("```\n</details>")

    text = "\n".join(lines) + "\n"
    WORK.mkdir(exist_ok=True)
    (WORK / "report.md").write_text(text, encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(text)
    print(text)


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------

def repo_files():
    """Every student file, as repo-relative posix paths."""
    found = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            found.append(Path(root, f).relative_to(REPO).as_posix())
    return found


def copy_sources():
    if WORK.exists():
        shutil.rmtree(WORK)
    if OUT.exists():
        shutil.rmtree(OUT)
    SRC.mkdir(parents=True)
    for rel in repo_files():
        dest = SRC / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, dest)


def read(rel):
    return (SRC / rel).read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")


def write(rel, text):
    (SRC / rel).write_text(text, encoding="utf-8")


ALL_FILES = []


IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")
NOT_TOPICS = {"manual.md", "design.md", "readme.md"}


MOVED = "moved"
AMBIGUOUS = "\x00"  # marks a hint about two files with the same name


def resolve(target, from_dir):
    """
    Find the file a link points to. Paths can be relative to the file the
    link is in, or written from the top folder (with or without a leading
    "/"). Returns (fixed_target, how): how is None when the link was fine,
    MOVED when the file was found in another folder by its name, or a
    sentence describing another fix. fixed_target is None if the file
    can't be found, and how then holds a hint.
    """
    path, frag = (target.split("#", 1) + [""])[:2]
    frag = "#" + frag if frag else ""
    path = urllib.parse.unquote(path)
    from_top = posixpath.normpath(path.lstrip("/"))
    here = from_top if path.startswith("/") else posixpath.normpath(posixpath.join(from_dir, path))

    def rel(found):
        return posixpath.relpath(found, from_dir or ".") + frag

    if here in ALL_FILES:
        return rel(here), None
    if from_top in ALL_FILES:
        return rel(from_top), None
    lower = {f.lower(): f for f in ALL_FILES}
    for cand in (here, from_top):
        if cand.lower() in lower:
            return rel(lower[cand.lower()]), "capital letters didn't match the file name"
    base = posixpath.basename(path).lower()
    same_name = [f for f in ALL_FILES if posixpath.basename(f).lower() == base]
    if len(same_name) == 1:
        return rel(same_name[0]), MOVED
    if len(same_name) > 1:
        listed = " and ".join(f"`/{f}`" for f in same_name[:3])
        return None, (f"{AMBIGUOUS} There's more than one file named `{posixpath.basename(path)}` ({listed}), "
                      "so the builder can't tell which one you mean. Write the full path from the "
                      f"top folder, like `/{same_name[0]}`.")
    if path.lower().endswith(".md"):
        pool = [f for f in ALL_FILES if f.lower().endswith(".md") and f.lower() not in NOT_TOPICS]
    elif path.lower().endswith(IMAGE_EXT):
        pool = [f for f in ALL_FILES if f.lower().endswith(IMAGE_EXT)]
    else:
        pool = ALL_FILES
    names = difflib.get_close_matches(posixpath.basename(path), [posixpath.basename(f) for f in pool], n=2, cutoff=0.6)
    hint = ""
    if names:
        hint = " Did you mean " + " or ".join(f"`{n}`" for n in names) + "?"
    return None, hint


def not_found(target, hint):
    """How to describe a link the builder couldn't follow."""
    if hint.startswith(AMBIGUOUS):
        return f"`{target}`, but that could mean more than one file.{hint[1:]}"
    return f"`{target}`, but that file doesn't exist.{hint}"


def note_fix(where, what, target, new, how):
    """Record a link the builder repaired. Moved files are summed up in one note."""
    if how == MOVED:
        R.moved.append(f"`{target}` in {where}")
    elif how:
        R.fixed(f"{where}: changed the {what} `{target}` to `{new}` ({how}).")


LINK_RE = re.compile(r"(!?)\[([^\]]*)\]\(\s*<?([^)\s>]+(?: [^)\s>]+)*)>?\s*(?:\"[^\"]*\")?\s*\)")


def is_external(target):
    return bool(re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I)) or target.startswith("#")


# --------------------------------------------------------------------------
# Map (manual.md)
# --------------------------------------------------------------------------

def check_map():
    """Returns [(topic path, link text)] for every topic in the menu."""
    if "manual.md" not in ALL_FILES:
        cands = [f for f in ALL_FILES if f.lower() == "manual.md"]
        if cands:
            shutil.copy2(SRC / cands[0], SRC / "manual.md")
            R.fixed(f"Your map file is named `{cands[0]}`; the builder used it as `manual.md`.")
        else:
            R.error("The file **manual.md** is missing. It holds your website's menu. "
                    "Create a file named `manual.md` (all lowercase) in the top folder of your repository.")
            return []

    text = read("manual.md")
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)  # drop any front matter
    lines = text.split("\n")

    if not any(re.match(r"#\s+\S", l) for l in lines):
        lines.insert(0, "# Game Manual\n")
        R.warn("**manual.md** has no title. Add a first line like `# Catan Game Manual` "
               "(a `#`, a space, then your title). The builder used \"Game Manual\" for now.")

    topics = []
    for i, line in enumerate(lines):
        # Tabs in the menu's indentation become 4 spaces
        lead = re.match(r"[ \t]*", line).group(0)
        if "\t" in lead:
            line = lead.replace("\t", "    ") + line[len(lead):]

        def fix(m):
            bang, label, target = m.groups()
            if is_external(target):
                return m.group(0)
            if bang:
                return ""
            dropped = (f" For now, \"{label}\" shows in your menu as a heading with no page.")
            if " " in target:
                R.warn(f"**manual.md** line {i + 1}: the link to `{target}` has a space in it. "
                       "File names can't contain spaces. Rename the file using hyphens "
                       "(like `set-up-the-board.md`) and change the link to match." + dropped)
                return label
            if not target.lower().endswith(".md"):
                R.warn(f"**manual.md** line {i + 1}: `{target}` isn't a Markdown file. "
                       "Every page in your menu must be a `.md` file." + dropped)
                return label
            new, how = resolve(target, "")
            if new is None:
                R.warn(f"**manual.md** line {i + 1}: the menu item \"{label}\" links to "
                       + not_found(target, how) + dropped)
                return label
            note_fix(f"**manual.md** line {i + 1}", "link", target, new, how)
            topics.append((new.split("#")[0], label))
            return f"[{label}]({new})"

        lines[i] = LINK_RE.sub(fix, line)

    write("manual.md", "\n".join(lines))
    write("_map.md", MAP_SCHEMA + "\n".join(lines))

    if not topics:
        R.error("**manual.md** doesn't link to any pages. Each menu item should look like "
                "`- [Setting up the game](topics/setup.md)`.")

    seen = set()
    for path, label in topics:
        if path in seen:
            R.warn(f"`{path}` appears in your menu more than once.")
        seen.add(path)

    in_menu = {p for p, _ in topics}
    loose = [f for f in ALL_FILES if f.startswith("topics/") and f.endswith(".md") and f not in in_menu]
    for f in loose:
        R.warn(f"`{f}` is not in your menu (manual.md), so it won't appear on your website.")

    return [(p, l) for p, l in dict.fromkeys(topics)]


# --------------------------------------------------------------------------
# Topics
# --------------------------------------------------------------------------

def check_topic(rel, label):
    text = read(rel)
    lines = text.split("\n")
    where = posixpath.dirname(rel)

    # Images and links inside the topic
    for i, line in enumerate(lines):
        def fix(m):
            bang, text_, target = m.groups()
            if is_external(target):
                return m.group(0)
            what = "picture" if bang else "link"
            if " " in target:
                R.warn(f"**{rel}** line {i + 1}: the {what} `{target}` has a space in its name. "
                       "Rename the file using hyphens instead of spaces, and change the "
                       f"{what} to match. For now, the {what} was left out.")
                return text_
            new, how = resolve(target, where)
            if new is None:
                msg = f"**{rel}** line {i + 1}: the {what} links to " + not_found(target, how)
                if bang:
                    R.warn(msg + " Upload the picture to the `images` folder, or fix its name. "
                           "For now, the picture was left out.")
                else:
                    R.warn(msg + " For now, the link was turned into plain text.")
                return text_
            note_fix(f"**{rel}** line {i + 1}", what, target, new, how)
            return f"{bang}[{text_}]({new})"

        lines[i] = LINK_RE.sub(fix, line)

    # Skip over any front matter
    start = 0
    if lines and lines[0].strip() == "---":
        for j in range(1, len(lines)):
            if lines[j].strip() == "---":
                start = j + 1
                break

    h1 = next((j for j in range(start, len(lines)) if re.match(r"#\s+\S", lines[j])), None)
    if h1 is None:
        lines.insert(start, f"# {label}\n")
        h1 = start
        R.warn(f"**{rel}** has no title. Add a first line that starts with `# ` "
               f"(like `# {label} {{.concept}}`). The builder used \"{label}\" for now.")

    # Topic type: "# Title {.task}"
    m = re.match(r"(#\s+.*?)\s*\{([^}]*)\}\s*$", lines[h1])
    title_line = m.group(1) if m else lines[h1].rstrip()
    ttype = None
    if m:
        words = re.findall(r"[a-zA-Z]+", m.group(2))
        known = [w.lower() for w in words if w.lower() in TOPIC_TYPES]
        if known:
            ttype = known[0]
            if m.group(2).strip() != f".{ttype}":
                R.fixed(f"**{rel}**: read `{{{m.group(2)}}}` as `{{.{ttype}}}`.")
        else:
            R.warn(f"**{rel}**: `{{{m.group(2)}}}` isn't a topic type. "
                   "Use `{.concept}`, `{.task}`, or `{.reference}` at the end of the title.")
    else:
        R.warn(f"**{rel}** doesn't say what type of topic it is. Add `{{.concept}}`, `{{.task}}`, "
               "or `{.reference}` to the end of the title line, like "
               f"`{title_line} {{.concept}}`.")
    lines[h1] = f"{title_line} {{.{ttype}}}" if ttype else title_line
    R.pages.append((label, rel, ttype or "none"))

    if ttype == "task":
        n = fix_task_steps(lines, h1 + 1, rel)
        if n:
            R.fixed(f"**{rel}**: {n} extra paragraph(s), picture(s), or note(s) indented under a "
                    "numbered step were shown as bullet points. In a DITA task, each step is one "
                    "instruction; put extra details in a bullet under the step, or after the list.")

    write(rel, "\n".join(lines))


def fix_task_steps(lines, start, rel):
    """
    DITA-OT's Markdown reader crashes when a numbered step in a task holds
    anything besides one paragraph and sub-lists. Turn each extra block
    into a sub-bullet instead. Returns how many blocks were changed.
    """
    changed = 0
    in_step = False
    after_blank = False
    in_fence = False
    for i in range(start, len(lines)):
        line = lines[i].replace("\t", "    ")
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        if stripped.startswith("```"):
            if not in_fence and in_step and indent >= 2 and rel not in CODE_IN_STEPS:
                CODE_IN_STEPS.append(rel)
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not stripped:
            after_blank = True
            continue
        if indent < 2 and re.match(r"\d+[.)]\s", stripped):
            in_step, after_blank = True, False
            continue
        if indent < 2:
            in_step, after_blank = False, False
            continue
        if in_step and after_blank and not re.match(r"([-*+]|\d+[.)])\s", stripped):
            body = re.sub(r"^>\s?", "", stripped)
            lines[i] = " " * max(indent, 3) + "- " + body
            changed += 1
        after_blank = False
    return changed


# --------------------------------------------------------------------------
# Design (design.md)
# --------------------------------------------------------------------------

CSS_COLORS = dict(x.split(":") for x in """
aliceblue:f0f8ff antiquewhite:faebd7 aqua:00ffff aquamarine:7fffd4 azure:f0ffff beige:f5f5dc
bisque:ffe4c4 black:000000 blanchedalmond:ffebcd blue:0000ff blueviolet:8a2be2 brown:a52a2a
burlywood:deb887 cadetblue:5f9ea0 chartreuse:7fff00 chocolate:d2691e coral:ff7f50
cornflowerblue:6495ed cornsilk:fff8dc crimson:dc143c cyan:00ffff darkblue:00008b darkcyan:008b8b
darkgoldenrod:b8860b darkgray:a9a9a9 darkgreen:006400 darkgrey:a9a9a9 darkkhaki:bdb76b
darkmagenta:8b008b darkolivegreen:556b2f darkorange:ff8c00 darkorchid:9932cc darkred:8b0000
darksalmon:e9967a darkseagreen:8fbc8f darkslateblue:483d8b darkslategray:2f4f4f
darkslategrey:2f4f4f darkturquoise:00ced1 darkviolet:9400d3 deeppink:ff1493 deepskyblue:00bfff
dimgray:696969 dimgrey:696969 dodgerblue:1e90ff firebrick:b22222 floralwhite:fffaf0
forestgreen:228b22 fuchsia:ff00ff gainsboro:dcdcdc ghostwhite:f8f8ff gold:ffd700
goldenrod:daa520 gray:808080 green:008000 greenyellow:adff2f grey:808080 honeydew:f0fff0
hotpink:ff69b4 indianred:cd5c5c indigo:4b0082 ivory:fffff0 khaki:f0e68c lavender:e6e6fa
lavenderblush:fff0f5 lawngreen:7cfc00 lemonchiffon:fffacd lightblue:add8e6 lightcoral:f08080
lightcyan:e0ffff lightgoldenrodyellow:fafad2 lightgray:d3d3d3 lightgreen:90ee90 lightgrey:d3d3d3
lightpink:ffb6c1 lightsalmon:ffa07a lightseagreen:20b2aa lightskyblue:87cefa
lightslategray:778899 lightslategrey:778899 lightsteelblue:b0c4de lightyellow:ffffe0
lime:00ff00 limegreen:32cd32 linen:faf0e6 magenta:ff00ff maroon:800000
mediumaquamarine:66cdaa mediumblue:0000cd mediumorchid:ba55d3 mediumpurple:9370db
mediumseagreen:3cb371 mediumslateblue:7b68ee mediumspringgreen:00fa9a mediumturquoise:48d1cc
mediumvioletred:c71585 midnightblue:191970 mintcream:f5fffa mistyrose:ffe4e1 moccasin:ffe4b5
navajowhite:ffdead navy:000080 oldlace:fdf5e6 olive:808000 olivedrab:6b8e23 orange:ffa500
orangered:ff4500 orchid:da70d6 palegoldenrod:eee8aa palegreen:98fb98 paleturquoise:afeeee
palevioletred:db7093 papayawhip:ffefd5 peachpuff:ffdab9 peru:cd853f pink:ffc0cb plum:dda0dd
powderblue:b0e0e6 purple:800080 rebeccapurple:663399 red:ff0000 rosybrown:bc8f8f
royalblue:4169e1 saddlebrown:8b4513 salmon:fa8072 sandybrown:f4a460 seagreen:2e8b57
seashell:fff5ee sienna:a0522d silver:c0c0c0 skyblue:87ceeb slateblue:6a5acd slategray:708090
slategrey:708090 snow:fffafa springgreen:00ff7f steelblue:4682b4 tan:d2b48c teal:008080
thistle:d8bfd8 tomato:ff6347 turquoise:40e0d0 violet:ee82ee wheat:f5deb3 white:ffffff
whitesmoke:f5f5f5 yellow:ffff00 yellowgreen:9acd32
""".split())

SYSTEM_FONTS = {
    "arial", "helvetica", "georgia", "times new roman", "times", "verdana", "tahoma",
    "trebuchet ms", "courier new", "palatino", "garamond", "comic sans ms", "impact",
    "system-ui", "serif", "sans-serif", "monospace",
}

DESIGN_KEYS = {
    "theme": "Theme",
    "style": "Style",
    "maincolor": "Main color",
    "accentcolor": "Accent color",
    "backgroundcolor": "Background color",
    "textcolor": "Text color",
    "headingfont": "Heading font",
    "bodyfont": "Body font",
    "textsize": "Text size",
    "corners": "Corners",
    "topiclabels": "Topic labels",
    "logo": "Logo",
    "footertext": "Footer text",
    "tagline": "Tagline",
    "themepicker": "Theme picker",  # testing only; see theme_picker()
}


def read_design():
    """Read 'Setting: value' lines from the top of design.md (before the first heading)."""
    values = {}
    if "design.md" not in ALL_FILES:
        R.warn("**design.md** is missing, so your site uses the parchment theme. "
               "Your instructor can give you a fresh copy.")
        return values
    for raw in read("design.md").split("\n"):
        if raw.lstrip().startswith("#"):
            break
        m = re.match(r"\s*[-*]?\s*\**\s*([A-Za-z][A-Za-z ]*?)\s*\**\s*[:=]\s*\**(.*?)\**\s*$", raw)
        if not m:
            continue
        key = re.sub(r"[^a-z]", "", m.group(1).lower())
        if key in DESIGN_KEYS and key not in values:
            values[key] = m.group(2).strip().strip("\"'`").strip()
        elif key not in DESIGN_KEYS and raw.strip():
            R.warn(f"**design.md**: the builder doesn't know the setting \"{m.group(1)}\", so it "
                   "skipped that line. Check the spelling of the words before the colon.")
    return values


def is_default(v):
    return not v or v.lower() in {"default", "theme", "none", "normal", "auto"}


def parse_color(v):
    """Return a #rrggbb string or None."""
    s = v.strip().lower().replace(" ", "")
    if s in CSS_COLORS:
        return "#" + CSS_COLORS[s]
    m = re.fullmatch(r"#?([0-9a-f]{6}|[0-9a-f]{3})", s)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return "#" + h
    m = re.fullmatch(r"rgb\((\d+),(\d+),(\d+)\)", s)
    if m and all(int(x) < 256 for x in m.groups()):
        return "#" + "".join(f"{int(x):02x}" for x in m.groups())
    return None


def luminance(hexcolor):
    def chan(c):
        c = int(c, 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    h = hexcolor.lstrip("#")
    r, g, b = (chan(h[i:i + 2]) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def readable_on(*colors):
    """White or near-black, whichever stays readable on every color given
    (more than one for a gradient)."""
    white = min(contrast(c, "#ffffff") for c in colors)
    dark = min(contrast(c, "#111111") for c in colors)
    return "#ffffff" if white >= dark else "#111111"


def read_theme(name):
    css = (HERE / "themes" / f"{name}.css").read_text(encoding="utf-8")
    return dict(re.findall(r"--([a-z-]+):\s*([^;]+);", css))


_font_cache = {}


def google_font(name):
    """Return the Google Fonts family name that works for `name`, or None."""
    if name in _font_cache:
        return _font_cache[name]
    result = None
    for candidate in dict.fromkeys([name, name.title(), " ".join(w.capitalize() for w in name.split())]):
        fam = urllib.parse.quote_plus(candidate)
        for query in (f"family={fam}:wght@400;700", f"family={fam}"):
            try:
                req = urllib.request.Request(f"https://fonts.googleapis.com/css2?{query}&display=swap",
                                             headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status == 200:
                        result = (candidate, query)
                        break
            except urllib.error.HTTPError:
                continue
            except Exception:
                # No internet: trust the name as typed
                result = (name, f"family={urllib.parse.quote_plus(name)}")
                break
        if result:
            break
    _font_cache[name] = result
    return result


def build_design():
    """Returns (css text, head html, settings dict)."""
    v = read_design()
    themes = sorted(p.stem for p in (HERE / "themes").glob("*.css"))

    theme = v.get("theme", "").lower().strip()
    if is_default(theme):
        theme = "parchment"
    if theme not in themes:
        close = difflib.get_close_matches(theme, themes, n=1)
        if close:
            R.fixed(f"**design.md**: read the theme \"{v.get('theme')}\" as \"{close[0]}\".")
            theme = close[0]
        else:
            R.warn(f"**design.md**: there's no theme called \"{v.get('theme')}\". "
                   f"Choose one of: {', '.join(themes)}. The builder used parchment.")
            theme = "parchment"
    R.design.append(("Theme", theme, ""))

    style_raw = v.get("style", "").lower()
    style = next((s_ for s_ in ("glass", "soft", "flat") if style_raw.startswith(s_)), None)
    if style is None:
        if not is_default(style_raw):
            R.warn(f"**design.md**: Style \"{v.get('style')}\" isn't glass, soft, or flat. "
                   "The builder used glass.")
        style = "glass"
    R.design.append(("Style", style, ""))
    t = read_theme(theme)

    colors = {}
    for key, var in (("maincolor", "main"), ("accentcolor", "accent"),
                     ("backgroundcolor", "bg"), ("textcolor", "text")):
        raw = v.get(key, "")
        label = DESIGN_KEYS[key]
        if is_default(raw):
            colors[var] = t[var]
            R.design.append((label, t[var], "theme"))
            continue
        c = parse_color(raw)
        if c:
            colors[var] = c
            R.design.append((label, c, f"from \"{raw}\""))
        else:
            colors[var] = t[var]
            R.design.append((label, t[var], "theme"))
            R.warn(f"**design.md**: \"{raw}\" isn't a color the builder knows, so {label} uses "
                   "the theme's color. Try a color name like `navy` or a hex code like `#1a5276`.")

    if contrast(colors["text"], colors["bg"]) < 4.5:
        R.warn(f"**design.md**: your text color and background color are too close "
               f"(contrast {contrast(colors['text'], colors['bg']):.1f} to 1; aim for at least 4.5). "
               "Some readers will struggle to read your pages. Try a darker text or a lighter background.")
    if contrast(colors["accent"], colors["bg"]) < 3:
        R.warn("**design.md**: links (accent color) are hard to see on your background. "
               "Try a darker or brighter accent color.")
    if contrast(colors["main"], colors["bg"]) < 3:
        R.warn("**design.md**: headings (main color) are hard to see on your background. "
               "Try a different main color.")

    fonts_to_load = []

    def font(key, var):
        raw = v.get(key, "")
        label = DESIGN_KEYS[key]
        theme_font = t[var].strip()
        name = theme_font if is_default(raw) else re.sub(r"[^A-Za-z0-9 ]", "", raw).strip()
        if name.lower() in SYSTEM_FONTS:
            R.design.append((label, name, "built-in font"))
            return name
        g = google_font(name)
        if g:
            fonts_to_load.append(g[1])
            R.design.append((label, g[0], "theme" if is_default(raw) else f"from \"{raw}\""))
            return g[0]
        R.warn(f"**design.md**: couldn't find the font \"{raw}\" on fonts.google.com, so {label} "
               "uses the theme's font. Check the spelling against the Google Fonts website.")
        fallback = google_font(theme_font)
        if fallback:
            fonts_to_load.append(fallback[1])
        R.design.append((label, theme_font, "theme"))
        return theme_font

    heading = font("headingfont", "heading-font")
    body = font("bodyfont", "body-font")

    size_raw = v.get("textsize", "").lower()
    size = {"small": "93.75%", "smaller": "93.75%", "medium": "100%", "normal": "100%",
            "large": "112.5%", "big": "112.5%", "larger": "112.5%", "extra large": "125%",
            "huge": "125%"}.get(size_raw)
    if size is None:
        if not is_default(size_raw):
            R.warn(f"**design.md**: Text size \"{v.get('textsize')}\" isn't small, medium, or large. "
                   "The builder used medium.")
        size, size_raw = "100%", "medium"
    R.design.append(("Text size", size_raw, ""))

    corners_raw = v.get("corners", "").lower()
    if corners_raw.startswith(("square", "sharp", "none", "straight")):
        radius, corners_raw = "0", "square"
    else:
        if corners_raw and not corners_raw.startswith("round") and not is_default(corners_raw):
            R.warn(f"**design.md**: Corners \"{v.get('corners')}\" isn't rounded or square. "
                   "The builder used rounded.")
        radius, corners_raw = "8px", "rounded"
    R.design.append(("Corners", corners_raw, ""))

    labels_raw = v.get("topiclabels", "show").lower()
    show_labels = not labels_raw.startswith(("hide", "no", "off", "false"))
    R.design.append(("Topic labels", "show" if show_labels else "hide", ""))

    logo = None
    logo_raw = v.get("logo", "")
    if not is_default(logo_raw):
        cand = logo_raw if "/" in logo_raw else f"images/{logo_raw}"
        new, _ = resolve(cand, "")
        if new and not new.lower().endswith(IMAGE_EXT):
            new = None
        if new:
            logo = new
            R.design.append(("Logo", new, ""))
        else:
            R.warn(f"**design.md**: couldn't find the logo picture \"{logo_raw}\". Upload it to the "
                   "`images` folder and write its exact file name (like `logo.png`).")

    footer = "" if is_default(v.get("footertext", "")) else v.get("footertext", "")
    R.design.append(("Footer text", html.escape(footer) or "(none)", ""))
    tagline = "" if is_default(v.get("tagline", "")) else v.get("tagline", "")
    R.design.append(("Tagline", html.escape(tagline) or "(none)", ""))

    def stack(name):
        return f'"{name}", system-ui, sans-serif'

    css = (HERE / "base.css").read_text(encoding="utf-8")
    css += f"""
/* ---------- Settings from design.md (theme: {theme}) ---------- */
:root {{
  --bg: {colors['bg']};
  --text: {colors['text']};
  --main: {colors['main']};
  --on-main: {readable_on(colors['main'])};
  --accent: {colors['accent']};
  --on-accent: {readable_on(colors['accent'])};
  --on-grad: {readable_on(colors['main'], colors['accent'])};
  --heading-font-stack: {stack(heading)};
  --body-font-stack: {stack(body)};
  --heading-scale: {t.get('heading-scale', '1') if is_default(v.get('headingfont', '')) else '1'};
  --radius: {radius};
  --base-size: {size};
}}
"""
    head = ['<meta name="viewport" content="width=device-width, initial-scale=1">']
    if fonts_to_load:
        head.append('<link rel="preconnect" href="https://fonts.googleapis.com">')
        head.append('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')
        for q in dict.fromkeys(fonts_to_load):
            head.append(f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?{html.escape(q)}&amp;display=swap">')
    head.append('<link rel="stylesheet" href="SITEROOT__/_theme/site.css">')

    picker = ""
    if v.get("themepicker", "").lower().startswith(("show", "on", "yes", "true")):
        p_css, p_head, picker = theme_picker(themes)
        css += p_css
        head.append(p_head)

    return css, "\n".join(head), {"logo": logo, "footer": footer, "labels": show_labels,
                                    "style": style, "tagline": tagline, "picker": picker}


def theme_picker(themes):
    """TESTING ONLY: a floating menu for previewing every theme and style.
    Turned on by an undocumented "Theme picker: show" line in design.md.
    To remove it: delete this function, its call in build_design(), the
    "themepicker" key in DESIGN_KEYS, and the "picker" line in finish_site().
    Returns (extra css, extra head html, widget html)."""
    R.warn("**Theme picker is on.** This is a testing tool. Delete the \"Theme picker\" line "
           "from design.md before students see this site.")
    css = ["\n/* ---------- Theme picker (testing only) ---------- */"]
    fonts = []
    for name in themes:
        t = read_theme(name)
        faces = []
        for var in ("heading-font", "body-font"):
            g = google_font(t[var].strip())
            if g:
                fonts.append(g[1])
            faces.append(g[0] if g else t[var].strip())
        css.append(f"""html[data-theme="{name}"] {{
  --bg: {t['bg']}; --text: {t['text']}; --main: {t['main']}; --accent: {t['accent']};
  --on-main: {readable_on(t['main'])}; --on-accent: {readable_on(t['accent'])};
  --on-grad: {readable_on(t['main'], t['accent'])};
  --heading-font-stack: "{faces[0]}", system-ui, sans-serif;
  --body-font-stack: "{faces[1]}", system-ui, sans-serif;
  --heading-scale: {t.get('heading-scale', '1')};
}}""")
    css.append("""
.theme-picker {
  position: fixed; right: 1rem; bottom: 1rem; z-index: 50;
  display: flex; flex-wrap: wrap; gap: .5rem; align-items: center;
  padding: .5rem .75rem; max-width: calc(100vw - 2rem);
  font: 600 .8rem/1.2 system-ui, sans-serif; color: var(--text);
  background: var(--surface-strong); border: 1px solid var(--line);
  border-radius: 999px; box-shadow: var(--shadow);
  -webkit-backdrop-filter: var(--blur); backdrop-filter: var(--blur);
}
.theme-picker select {
  font: inherit; color: var(--text); background: var(--bg);
  border: 1px solid var(--line); border-radius: 999px; padding: .3rem .6rem;
}
.theme-picker span { opacity: .7; }
@media print { .theme-picker { display: none; } }""")

    head = [f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?{html.escape(q)}&amp;display=swap">'
            for q in dict.fromkeys(fonts)]
    # Every student site shares one origin, so keep the choice per repo.
    head.append("""<script>
(function () {
  var key = "themePicker:" + location.pathname.split("/")[1];
  try { var s = JSON.parse(localStorage.getItem(key) || "{}"); } catch (e) { s = {}; }
  if (s.theme) document.documentElement.dataset.theme = s.theme;
  window.__picker = { key: key, saved: s };
})();
</script>""")
    options = "".join(f'<option value="{n}">{n}</option>' for n in themes)
    widget = f"""<div class="theme-picker" role="group" aria-label="Theme picker (testing only)">
<span>Preview</span>
<select id="tp-theme" aria-label="Theme"><option value="">design.md</option>{options}</select>
<select id="tp-style" aria-label="Style"><option value="">design.md</option>
<option value="glass">glass</option><option value="soft">soft</option><option value="flat">flat</option></select>
</div>
<script>
(function () {{
  var p = window.__picker, s = p.saved, body = document.body;
  var built = (body.className.match(/style-(\\w+)/) || [])[1];
  var theme = document.getElementById("tp-theme"), style = document.getElementById("tp-style");
  function apply() {{
    if (s.theme) document.documentElement.dataset.theme = s.theme;
    else delete document.documentElement.dataset.theme;
    body.className = body.className.replace(/style-\\w+/, "style-" + (s.style || built));
    theme.value = s.theme || ""; style.value = s.style || "";
  }}
  function save() {{
    s = {{ theme: theme.value, style: style.value }};
    try {{ localStorage.setItem(p.key, JSON.stringify(s)); }} catch (e) {{}}
    apply();
  }}
  theme.onchange = style.onchange = save;
  apply();
}})();
</script>"""
    return "\n".join(css) + "\n", "\n".join(head), widget


# --------------------------------------------------------------------------
# DITA-OT
# --------------------------------------------------------------------------

def run_dita():
    out = WORK / "out"
    cmd = ["docker", "run", "--rm"]
    if hasattr(os, "getuid"):
        cmd += ["--user", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp"]
    cmd += ["-v", f"{WORK}:/work", "-w", "/work", DITA_IMAGE,
            "--input=src/_map.md", "--format=html5", "--output=out",
            "--nav-toc=full", "--temp=/tmp/dita-temp"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    log = proc.stdout + proc.stderr
    (WORK / "dita-log.txt").write_text(log, encoding="utf-8")
    R.dita_log = log

    if "Attribute \"class\" was already specified for element \"info\"" in log:
        where = (" in " + ", ".join(f"**{f}**" for f in CODE_IN_STEPS)) if CODE_IN_STEPS else \
            " in one of your task topics"
        R.error(f"A numbered step{where} has something extra indented under it that the builder "
                "couldn't fix (usually a code block made with ``` marks). Move it after the "
                "numbered list, or remove the ``` marks.")
    ok = proc.returncode == 0 and (out / "index.html").exists()
    if not ok and not R.errors:
        R.error("DITA-OT couldn't build your site, and the builder doesn't recognize the problem. "
                "Open the **Technical details** below and share them with your instructor.")
    return ok


# --------------------------------------------------------------------------
# Finish the pages
# --------------------------------------------------------------------------

def finish_site(title, css, head, opts):
    shutil.copytree(WORK / "out", OUT)
    (OUT / "_theme").mkdir(exist_ok=True)
    (OUT / "_theme" / "site.css").write_text(css, encoding="utf-8")

    logo_html = ""
    if opts["logo"]:
        ext = posixpath.splitext(opts["logo"])[1]
        shutil.copy2(SRC / opts["logo"], OUT / "_theme" / f"logo{ext}")
        logo_html = f'<img src="SITEROOT__/_theme/logo{ext}" alt="">'

    search_box = ('<div class="site-search" role="search">'
                  '<input type="search" placeholder="Search the manual" aria-label="Search the manual" '
                  'autocomplete="off" spellcheck="false">'
                  '<div class="search-results" hidden></div></div>')
    header = (f'<header role="banner"><div class="site-header">'
              f'<a class="site-title" href="SITEROOT__/index.html">{logo_html}{html.escape(title)}</a>'
              f'{search_box}<a class="menu-link" href="#site-menu">Menu</a></div></header>')
    search_index = []

    try:
        from zoneinfo import ZoneInfo
        now = datetime.datetime.now(ZoneInfo("America/New_York"))
        stamp = now.strftime("%B %-d, %Y at %-I:%M %p Eastern")
    except Exception:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%B %d, %Y at %H:%M UTC")
    footer_bits = []
    if opts["footer"]:
        footer_bits.append(f"<p>{html.escape(opts['footer'])}</p>")
    n = len(R.warnings)
    report_link = (f'<a href="SITEROOT__/build-report.html">Build report: {n} thing{"s" if n != 1 else ""} to check</a>'
                   if n else '<a href="SITEROOT__/build-report.html">Build report</a>')
    footer_bits.append(f"<p>Last updated {stamp}. Built with DITA-OT. {report_link}</p>")
    footer = f'<footer role="contentinfo">{"".join(footer_bits)}</footer>'
    # Long menus scroll inside their own box; start with the current page in view.
    footer += ('<script>(function(){var n=document.querySelector("nav.toc"),'
               'a=n&&n.querySelector("li.active > a");'
               'if(a&&n.scrollHeight>n.clientHeight)n.scrollTop=a.offsetTop-n.clientHeight/3;})();</script>')

    labels = {"conbody": "Concept", "taskbody": "Task", "refbody": "Reference"}

    (OUT / "build-report.html").write_text(
        f'<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>Build report</title>'
        f'</head><body><main role="main"><article>{report_html()}</article></main></body></html>',
        encoding="utf-8")

    for page in OUT.rglob("*.html"):
        depth = len(page.relative_to(OUT).parts) - 1
        root = "/".join([".."] * depth) or "."
        doc = page.read_text(encoding="utf-8")
        name = page.relative_to(OUT).as_posix()
        is_home = name == "index.html"
        page_class = {"index.html": " home-page", "build-report.html": " report-page"}.get(name, "")

        if not page_class:
            search_index.append(search_record(name, doc))
        doc = doc.replace("</head>", head + '<script src="SITEROOT__/_theme/search.js" defer></script>'
                          + "</head>", 1)
        doc = doc.replace("<body", f'<body class="style-{opts["style"]}{page_class}"', 1)
        page_header = header.replace('<a class="menu-link" href="#site-menu">Menu</a>', "") if page_class else header
        doc = re.sub(r"(<body[^>]*>)", lambda m: m.group(1) + page_header, doc, count=1)
        doc = doc.replace("</body>", footer + opts["picker"] + "</body>", 1)
        doc = doc.replace('<nav class="toc"', '<nav class="toc" id="site-menu"', 1)

        if is_home:
            doc = re.sub(r"(</header>)(.*)(<footer)", r'\1<main class="home">\2</main>\3', doc, count=1, flags=re.S)
            tagline = f'<p class="tagline">{html.escape(opts["tagline"])}</p>' if opts["tagline"] else ""
            doc = re.sub(r'(<h1 class="title topictitle1">.*?</h1>)',
                         lambda m: f'<div class="home-hero">{m.group(1)}{tagline}{search_box}</div>',
                         doc, count=1, flags=re.S)

        if opts["labels"]:
            m = re.search(r'<div class="body (conbody|taskbody|refbody)', doc)
            if m:
                doc = doc.replace('<h1 class="title topictitle1"',
                                  f'<span class="topic-label">{labels[m.group(1)]}</span>'
                                  '<h1 class="title topictitle1"', 1)

        doc = doc.replace("SITEROOT__", root)
        page.write_text(doc, encoding="utf-8")

    shutil.copy2(HERE / "search.js", OUT / "_theme" / "search.js")
    (OUT / "_theme" / "search-index.js").write_text(
        "window.SEARCH_INDEX = " + json.dumps(search_index, ensure_ascii=False) + ";\n", encoding="utf-8")


class _MenuTrail(html.parser.HTMLParser):
    """Finds the menu sections ("Cards", "Crew") above the current page in the nav."""
    def __init__(self):
        super().__init__()
        self.stack, self.trail, self.in_span = [], None, False

    def handle_starttag(self, tag, attrs):
        if tag == "li":
            self.stack.append(None)
            if self.trail is None and "active" in (dict(attrs).get("class") or ""):
                self.trail = [t for t in self.stack[:-1] if t]
        elif tag == "span" and self.stack:
            self.in_span = True

    def handle_endtag(self, tag):
        if tag == "li" and self.stack:
            self.stack.pop()
        elif tag == "span":
            self.in_span = False

    def handle_data(self, data):
        if self.in_span and data.strip():
            self.stack[-1] = (self.stack[-1] or "") + data.strip()


def search_record(name, doc):
    """One page's entry in the search index: its title, menu section, and text."""
    m = re.search(r'<h1 class="title topictitle1"[^>]*>(.*?)</h1>', doc, flags=re.S)
    title = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else name
    body = re.search(r"<main[^>]*>(.*)</main>", doc, flags=re.S)
    body = body.group(1) if body else ""
    body = re.sub(r'<h1 class="title topictitle1".*?</h1>', " ", body, count=1, flags=re.S)
    body = re.sub(r"<(script|style)\b.*?</\1>", " ", body, flags=re.S)
    heads = [html.unescape(re.sub(r"<[^>]+>", "", h)).strip()
             for h in re.findall(r"<h[2-4][^>]*>(.*?)</h[2-4]>", body, flags=re.S)]
    body = re.sub(r"</t[dh]>", " · ", body)  # keep table cells apart in snippets
    text = html.unescape(re.sub(r"<[^>]+>", " ", body))
    text = re.sub(r"\s+", " ", text).strip()
    nav = re.search(r'<nav class="toc".*?</nav>', doc, flags=re.S)
    trail = []
    if nav:
        p = _MenuTrail()
        p.feed(nav.group(0))
        trail = p.trail or []
    return {"u": name, "t": title, "s": " › ".join(trail), "h": " · ".join(heads), "x": text[:6000]}


def inline(text):
    """The few bits of Markdown used in report messages, as HTML."""
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", text)


def report_html():
    parts = ['<h1 class="title topictitle1">Build report</h1>',
             "<p>This page is for you, the writer. It lists what the website builder noticed the "
             "last time it built your site.</p>"]
    for title, items in (("Things to check", R.warnings),
                         ("Small mistakes the builder fixed for you", R.fixes)):
        parts.append(f"<h2>{title}</h2>")
        if items:
            parts.append("<ul>" + "".join(f"<li>{inline(i)}</li>" for i in items) + "</ul>")
        else:
            parts.append("<p>None. Nice work!</p>")
    if R.fixes:
        parts.append("<p><em>Your files were not changed. The builder fixed these in its own copy, "
                     "so you can fix them in your files whenever you like.</em></p>")
    if R.pages:
        counts = {t: sum(1 for p in R.pages if p[2] == t) for t in TOPIC_TYPES + ("none",)}
        summary = ", ".join(f"{n} {t}" for t, n in counts.items() if n and t != "none")
        if counts["none"]:
            summary += f", {counts['none']} without a type"
        parts.append(f"<h2>Your pages</h2><p>{len(R.pages)} pages in your menu: {summary}. "
                     "Compare this list with your content inventory.</p>")
        parts.append("<table><thead><tr><th>#</th><th>Menu item</th><th>Type</th><th>File</th>"
                     "</tr></thead><tbody>")
        for n, (label, rel, ttype) in enumerate(R.pages, 1):
            parts.append(f"<tr><td>{n}</td><td>{html.escape(label)}</td><td>{ttype}</td>"
                         f"<td><code>{html.escape(rel)}</code></td></tr>")
        parts.append("</tbody></table>")
    parts.append("<h2>Design settings used</h2><table><thead><tr><th>Setting</th><th>Used</th>"
                 "<th>Note</th></tr></thead><tbody>")
    for name, value, note in R.design:
        parts.append(f"<tr><td>{name}</td><td>{value}</td><td>{html.escape(note)}</td></tr>")
    parts.append("</tbody></table>")
    return "\n".join(parts)


def map_title():
    for line in read("manual.md").split("\n"):
        m = re.match(r"#\s+(.*?)\s*$", line)
        if m:
            return m.group(1)
    return "Game Manual"


# --------------------------------------------------------------------------

def main():
    global ALL_FILES
    copy_sources()
    ALL_FILES = repo_files()

    spaced = [f for f in ALL_FILES if " " in f]
    for f in spaced:
        R.warn(f"The file `{f}` has a space in its name. Spaces break links; rename it using "
               "hyphens instead (like `my-picture.png`).")

    topics = check_map()
    for rel, label in topics:
        check_topic(rel, label)
    if R.moved:
        R.fixed(f"{len(R.moved)} link(s) pointed to a file that's in a different folder, and the "
                "builder found the file by its name: " + "; ".join(R.moved) + ". This is fine, but "
                "if two files ever share a name, the builder will need the full path.")

    css, head, opts = build_design()

    if R.errors:
        write_report(False)
        return 1

    ok = run_dita()
    if ok:
        finish_site(map_title(), css, head, opts)
    write_report(ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
