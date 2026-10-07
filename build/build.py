#!/usr/bin/env python3
"""Build mattmaltman.github.io/index.html from build/data.json + build/template.html.

Usage: python3 build/build.py   (standard library only)
"""
import csv
import json
import math
import re
import sys
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data.json"
TEMPLATE = HERE / "template.html"
OUT = HERE.parent / "index.html"

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

NAV = [  # (label, id, children)
    ("Research", None, [("Working Papers", "working-papers"), ("Publications", "publications")]),
    ("Long-Form", "long-form", []),
    ("Commentary", "commentary", []),
    ("Policy Work", "policy", []),
    ("Media", "media", []),
]


def t(s):
    """Escape text content (apostrophes left as-is)."""
    return escape(s, quote=False)


def a(s):
    """Escape an attribute value."""
    return escape(s, quote=True)


def fmt_date(d):
    if not d:
        return ""
    parts = str(d).split("-")
    if len(parts) == 1:
        return parts[0]
    return f"{MONTHS[int(parts[1]) - 1]} {parts[0]}"


def sort_key(d):
    """Newest first; undated last."""
    return str(d) if d else ""


def oxford(names):
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + ", and " + names[-1]


def meta_text(e, default_details=""):
    bits = []
    if e.get("coauthors"):
        bits.append(f"with {t(oxford(e['coauthors']))}.")
    venue = e.get("venue")
    details = e.get("details") or default_details
    if venue:
        s = f'<span class="venue">{t(venue)}</span>'
        if details:
            s += f", {t(details)}"
        bits.append(s + ".")
    elif details:
        bits.append(t(details) + ".")
    return " ".join(bits)


def tag_line(label, items):
    if not items:
        return ""
    links = " · ".join(
        f'<a href="{a(m["url"])}" title="{a(m["title"])}">{t(m["outlet"])}</a>' for m in items
    )
    return f'<span class="tags"><span class="lbl">{label}</span>{links}</span>'


def see_also_line(e):
    """Companion newsletter pieces, e.g. 'See also: Title, e61 Newsletter, Sep 2025'."""
    items = e.get("seeAlso") or []
    if not items:
        return ""
    links = " · ".join(
        f'<a href="{a(s["url"])}">{t(s["title"])}</a>, {t(s.get("venue") or "e61 Newsletter")}'
        + (f', {fmt_date(s.get("date"))}' if s.get("date") else "")
        for s in items
    )
    return f'<span class="tags"><span class="lbl">See also</span>{links}</span>'


def tags(e):
    return see_also_line(e) + tag_line("Media", (e.get("media") or []) + (e.get("citedBy") or []))


def title_html(e, cls="title"):
    c = f' class="{cls}"' if cls else ""
    if e.get("url"):
        return f'<a{c} href="{a(e["url"])}">{t(e["title"])}</a>'
    return f'<span{c}>{t(e["title"])}</span>'


# ---------------------------------------------------------------- charts
# Inline SVG line charts, built from build/figures/<slug>.csv at build time.
# All colours come from CSS classes (.fig-*) in template.html, so light and
# dark mode follow the page's custom properties. Geometry is in viewBox units.
FIG_DIR = HERE / "figures"
FIG_W, FIG_H = 640, 320
FIG_FONT_MAX = 20     # largest font (viewBox units) the CSS uses; for layout
FIG_FONT_END = 15     # largest font at which end labels are shown (<=700px)
CH_W = 0.6            # IBM Plex Mono advance width, em


def text_w(s, font):
    return len(s) * CH_W * font


def num(v):
    """Compact number for SVG coordinates."""
    return f"{v:.1f}".rstrip("0").rstrip(".") if v != int(v) else str(int(v))


def nice_step(span, target=5):
    raw = span / target
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def fmt_tick(v):
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:g}"


def load_figure_csv(slug):
    path = FIG_DIR / f"{slug}.csv"
    if not path.exists():
        sys.exit(f"Figure CSV not found: {path}")
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        sys.exit(f"Figure CSV is empty: {path}")
    return rows, list(rows[0].keys())[0]


def render_figure(f):
    rows, xcol = load_figure_csv(f["slug"])
    series = f["series"]
    for s in series:
        if s["column"] not in rows[0]:
            sys.exit(f"Column {s['column']!r} not in {f['slug']}.csv")
    xs = [float(r[xcol]) for r in rows]
    pts = {s["column"]: [(float(r[xcol]), float(r[s["column"]])) for r in rows if r[s["column"]].strip()]
           for s in series}
    events, bands = f.get("events") or [], f.get("bands") or []
    x0, x1 = min(xs), max(xs)

    # y scale: nice ticks, from 0 unless yMin given
    ys = [y for p in pts.values() for _, y in p]
    lo = f.get("yMin", 0 if min(ys) >= 0 else min(ys))
    hi = f.get("yMax", max(ys))
    step = f.get("yStep") or nice_step(hi - lo)
    lo = math.floor(lo / step) * step
    hi = math.ceil(hi / step) * step
    yticks = []
    v = lo
    while v <= hi + step / 1e6:
        yticks.append(round(v, 10))
        v += step
    # optional exact axis, e.g. to match the paper: explicit ticks and plot range
    if f.get("yTicks"):
        yticks = f["yTicks"]
    if f.get("yRange"):
        lo, hi = f["yRange"]

    # x ticks: every xStep years (default 5); every other one is hidden on phones
    xstep = f.get("xStep", 5)
    xticks = [v for v in range(math.ceil(x0 / xstep) * xstep, int(x1) + 1, xstep)]

    # margins: left fits tick labels at the largest font; right fits end labels
    left = max(text_w(fmt_tick(v), FIG_FONT_MAX) for v in yticks) + 10
    right = max(text_w(s["label"], FIG_FONT_END) for s in series) + 16
    # top: rows of labels above the plot; the y label takes the left of row 0,
    # event / band labels pack into the first row where they don't collide
    marks = [(b["from"], b["label"]) for b in bands if b.get("label")] + \
            [(e["x"], e["label"]) for e in events if e.get("label")]
    row_h = FIG_FONT_MAX * 1.2
    rows_used = [[(0, text_w(f.get("yLabel", ""), FIG_FONT_MAX) + 6)]]  # occupied spans per row
    placed = []
    plot_w = FIG_W - left - right

    def sx(x):
        return left + (x - x0) / (x1 - x0) * plot_w

    for x, label in sorted(marks):
        w = text_w(label, FIG_FONT_MAX)
        px = sx(x)
        anchor, a0 = ("start", px + 4) if px + 4 + w <= FIG_W else ("end", px - 4 - w)
        span = (a0 - 6, a0 + w + 6)
        for i, occ in enumerate(rows_used):
            if all(span[1] <= o0 or span[0] >= o1 for o0, o1 in occ):
                occ.append(span)
                break
        else:
            rows_used.append([span])
            i = len(rows_used) - 1
        placed.append((px, label, anchor, i))
    top = row_h * len(rows_used) + 8
    bottom = FIG_FONT_MAX * 1.2 + 10
    plot_h = FIG_H - top - bottom

    def sy(y):
        return top + (hi - y) / (hi - lo) * plot_h

    o = []
    o.append(f'<svg class="fig-svg" viewBox="0 0 {FIG_W} {FIG_H}" role="img" aria-label="{a(f["takeaway"])}">')
    # y label (top-left), above the plot
    o.append(f'<text class="fig-ylab" x="0" y="{num(row_h * 0.8)}">{t(f.get("yLabel", ""))}</text>')
    for b in bands:
        bx0, bx1 = sx(max(b["from"], x0)), sx(min(b["to"], x1))
        o.append(f'<rect class="fig-band" x="{num(bx0)}" y="{num(top)}" width="{num(bx1 - bx0)}" height="{num(plot_h)}"/>')
    for v in yticks:
        y = sy(v)
        cls = "fig-base" if v == lo else "fig-grid"
        o.append(f'<line class="{cls}" x1="{num(left)}" x2="{num(left + plot_w)}" y1="{num(y)}" y2="{num(y)}"/>')
        o.append(f'<text class="fig-tick" x="{num(left - 8)}" y="{num(y)}" dy=".35em" text-anchor="end">{fmt_tick(v)}</text>')
    for v in xticks:
        minor = " fig-minor" if (v // xstep) % 2 else ""
        o.append(f'<text class="fig-tick{minor}" x="{num(sx(v))}" y="{num(FIG_H - 6)}" text-anchor="middle">{v}</text>')
    for e in events:
        x = sx(e["x"])
        o.append(f'<line class="fig-event" x1="{num(x)}" x2="{num(x)}" y1="{num(top - 4)}" y2="{num(top + plot_h)}"/>')
    for px, label, anchor, i in placed:
        ty = row_h * i + row_h * 0.8
        tx = px + 4 if anchor == "start" else px - 4
        o.append(f'<text class="fig-mark" x="{num(tx)}" y="{num(ty)}" text-anchor="{anchor}">{t(label)}</text>')
    # series: comparison first so the main series draws on top
    ends = []
    for s in sorted(series, key=lambda s: s.get("role") == "main"):
        p = pts[s["column"]]
        cls = "fig-main" if s.get("role") == "main" else "fig-cmp"
        if s.get("dashed"):
            cls += " fig-dash"
        d = "M" + " L".join(f"{num(sx(x))},{num(sy(y))}" for x, y in p)
        o.append(f'<path class="fig-line {cls}" d="{d}"/>')
        ex, ey = p[-1]
        o.append(f'<circle class="fig-dot {cls}" cx="{num(sx(ex))}" cy="{num(sy(ey))}" r="3"/>')
        ends.append([sy(ey), s["label"], cls.split()[0]])
    # end labels, nudged apart if they collide
    ends.sort()
    gap = FIG_FONT_END * 1.15
    for i in range(1, len(ends)):
        if ends[i][0] - ends[i - 1][0] < gap:
            ends[i][0] = ends[i - 1][0] + gap
    for y, label, cls in ends:
        o.append(f'<text class="fig-end {cls}-lab" x="{num(left + plot_w + 8)}" y="{num(y)}" dy=".35em">{t(label)}</text>')
    # native hover tooltips (no JS): one invisible hit target per year
    xs_sorted = sorted(set(xs))
    for i, x in enumerate(xs_sorted):
        xa = sx(xs_sorted[i - 1]) if i else sx(x)
        xb = sx(xs_sorted[i + 1]) if i + 1 < len(xs_sorted) else sx(x)
        hx0, hx1 = (xa + sx(x)) / 2, (sx(x) + xb) / 2
        vals = [f"{s['label']} {fmt_val(dict(pts[s['column']]).get(x))}" for s in series]
        o.append(f'<rect class="fig-hit" x="{num(hx0)}" y="{num(top)}" width="{num(max(hx1 - hx0, 1))}" '
                 f'height="{num(plot_h)}"><title>{num(x)}: {t(", ".join(vals))}</title></rect>')
    o.append("</svg>")
    svg = "".join(o)

    key = "".join(
        f'<span><i class="fig-sw {"fig-main" if s.get("role") == "main" else "fig-cmp"}'
        f'{" fig-dash" if s.get("dashed") else ""}"></i>{t(s["label"])}</span>'
        for s in series
    )
    head = "".join(f"<th>{t(s['label'])}</th>" for s in series)
    body = "".join(
        f"<tr><td>{num(x)}</td>" + "".join(f"<td>{fmt_val(dict(pts[s['column']]).get(x))}</td>" for s in series) + "</tr>"
        for x in xs_sorted
    )
    src = f' <span class="fig-src">Source: {t(f["source"])}</span>' if f.get("source") else ""
    # (figure, data toggle): the toggle sits with the paper info in chart rows
    figure = (
        '      <figure class="fig">'
        f'<p class="fig-key" aria-hidden="true">{key}</p>'
        f"{svg}"
        "</figure>"
    )
    data = (
        f'<details class="fig-data"><summary>Data</summary><table><thead><tr><th>{t(xcol.capitalize())}</th>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></details>"
    )
    return figure, data


def fmt_val(v):
    if v is None:
        return "n/a"
    return f"{v:,.2f}".rstrip("0").rstrip(".") if not float(v).is_integer() else f"{v:,.0f}"


def abstract_html(e):
    return f'<p class="abstract">{t(e["abstract"])}</p>' if e.get("abstract") else ""


def pub_item(e, extra=""):
    meta = meta_text(e)
    if e.get("figure"):
        # chart row: sticky paper info (left) + chart (right) on wide screens
        fig, data = render_figure(e["figure"])
        return (
            '    <li class="has-fig">\n'
            '      <div class="fig-info"><div class="fig-head">'
            f"{title_html(e)}<br>\n"
            f'      <span class="meta">{meta}</span>{tags(e)}{extra}</div>{abstract_html(e)}</div>\n'
            f"{fig}\n"
            "    </li>"
        )
    return (
        "    <li>\n"
        f"      {title_html(e)}<br>\n"
        f'      <span class="meta">{meta}</span>{tags(e)}{extra}{abstract_html(e)}\n'
        "    </li>"
    )


def render_pubs(entries):
    return "\n".join(pub_item(e) for e in entries)


def render_commentary(entries):
    out = []
    for e in sorted(entries, key=lambda x: sort_key(x.get("date")), reverse=True):
        e = dict(e, venue=e["outlet"], details=e.get("details") or fmt_date(e.get("date")))
        rel = e.get("related")
        extra = (
            f'<span class="related">On: <a href="{a(rel["url"])}">{t(rel["title"])}</a></span>'
            if rel else ""
        )
        out.append(pub_item(e, extra))
    return "\n".join(out)


def policy_li(e, sources):
    src = e["source"]
    if src not in sources:
        sys.exit(f"Unknown source {src!r} on {e['title']!r}")
    if src == "other" and not e.get("outlet"):
        sys.exit(f"Source 'other' needs an 'outlet': {e['title']!r}")
    e = dict(e)
    if src == "other" and not e.get("venue"):
        e["venue"] = e["outlet"]
    label = e["outlet"] if src == "other" else sources[src]["label"]
    meta = meta_text(e, fmt_date(e.get("date")))
    return (
        f'        <li><a class="src-{src}" href="{a(e["url"])}" data-source="{a(label)}">{t(e["title"])}</a>'
        f'<span class="meta">{meta}</span>{tags(e)}</li>'
    )


def render_policy(data):
    sources = data["sources"]
    show = int(data.get("policyShowFirst", 6))
    topics = data["policyTopics"]
    for e in data["policy"]:
        if e["topic"] not in topics:
            sys.exit(f"Unknown topic {e['topic']!r} on {e['title']!r}")
    blocks = []
    for topic in topics:
        items = [e for e in data["policy"] if e["topic"] == topic]
        if not items:
            continue
        items.sort(key=lambda x: sort_key(x.get("date")), reverse=True)  # stable
        lis = [policy_li(e, sources) for e in items]
        html = ["    <div class=\"topic\">", f"      <h3>{t(topic)}</h3>", "      <ul>"]
        html += lis[:show]
        html.append("      </ul>")
        if len(lis) > show:
            rest = len(lis) - show
            html.append(f"      <details><summary>Show {rest} more</summary>")
            html.append("      <ul>")
            html += lis[show:]
            html.append("      </ul>")
            html.append("      </details>")
        html.append("    </div>")
        blocks.append("\n".join(html))
    return "\n".join(blocks)


def render_legend(data):
    used = {e["source"] for e in data["policy"]}
    parts = []
    for key, s in data["sources"].items():
        if key == "other" and key not in used:
            continue
        parts.append(f'<span style="text-decoration-color:var(--src-{ {"e61-research":"research","e61-blog":"blog","ofe":"ofe","other":"other"}[key] })">{t(s["label"])}</span>')
    return '<span class="sep">·</span>'.join(parts)


def render_other_media(entries):
    out = []
    for m in sorted(entries, key=lambda x: sort_key(x.get("date")), reverse=True):
        date = fmt_date(m.get("date"))
        out.append(
            f'    <li><span class="kind">{t(m["kind"])}</span>{t(m["outlet"])}, '
            f'<a href="{a(m["url"])}">{t(m["title"])}</a>{", " + date if date else ""}.</li>'
        )
    return "\n".join(out)


def visible_nav(empty):
    """NAV with links to empty sections removed (and groups left with no children)."""
    out = []
    for label, sid, kids in NAV:
        if kids:
            kids = [(kl, kid) for kl, kid in kids if kid not in empty]
            if kids:
                out.append((label, sid, kids))
        elif sid not in empty:
            out.append((label, sid, kids))
    return out


def drop_section(html, sid):
    """Remove <section id="sid" ...>...</section> from the template."""
    new, n = re.subn(r'\n<section id="' + re.escape(sid) + r'"[^>]*>.*?</section>\n', "\n", html, flags=re.S)
    if n != 1:
        sys.exit(f"Could not find section #{sid} in template")
    return new


def render_side_nav(nav):
    lines = ['<nav class="toc" aria-label="Sections">', "  <ul>"]
    for label, sid, kids in nav:
        if kids:
            lines.append(f'    <li><span class="grp">{t(label)}</span>')
            lines.append("      <ul>")
            for kl, kid in kids:
                lines.append(f'        <li><a href="#{kid}">{t(kl)}</a></li>')
            lines.append("      </ul>")
            lines.append("    </li>")
        else:
            lines.append(f'    <li><a href="#{sid}">{t(label)}</a></li>')
    lines += ["  </ul>", "</nav>"]
    return "\n".join(lines)


def render_toc_row(nav):
    links = []
    for label, sid, kids in nav:
        target = sid or kids[0][1]
        links.append(f'<a href="#{target}">{t(label)}</a>')
    return '<nav class="toc-row" aria-label="Sections">' + "".join(links) + "</nav>"


NAV_SCRIPT = """<script>
(function(){
  if(!('IntersectionObserver' in window))return;
  var links=document.querySelectorAll('.toc a[href^="#"]');
  var map={},secs=[];
  links.forEach(function(l){var s=document.getElementById(l.getAttribute('href').slice(1));if(s){map[s.id]=l;secs.push(s);}});
  var vis={};
  function update(){
    var cur=null;
    for(var i=0;i<secs.length;i++){if(vis[secs[i].id]){cur=secs[i].id;break;}}
    if(!cur)return;
    links.forEach(function(l){l.classList.remove('active');l.removeAttribute('aria-current');});
    map[cur].classList.add('active');map[cur].setAttribute('aria-current','true');
  }
  var io=new IntersectionObserver(function(es){es.forEach(function(e){vis[e.target.id]=e.isIntersecting;});update();},{rootMargin:'-15% 0px -60% 0px'});
  secs.forEach(function(s){io.observe(s);});
})();
</script>"""


def main():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    tpl = TEMPLATE.read_text(encoding="utf-8")
    sections = {  # section id -> (placeholder, rendered list content)
        "working-papers": ("WORKING_PAPERS", render_pubs(data.get("workingPapers", []))),
        "publications": ("PUBLICATIONS", render_pubs(data.get("publications", []))),
        "long-form": ("LONG_FORM", render_pubs(data.get("longForm", []))),
        "commentary": ("COMMENTARY", render_commentary(data.get("commentary", []))),
        "policy": ("POLICY_TOPICS", render_policy(data)),
        "media": ("OTHER_MEDIA", render_other_media(data.get("otherMedia", []))),
    }
    empty = {sid for sid, (_, html) in sections.items() if not html.strip()}
    out = tpl
    for sid in empty:  # skip empty sections entirely
        out = drop_section(out, sid)
    nav = visible_nav(empty)
    repl = {"SIDE_NAV": render_side_nav(nav), "TOC_ROW": render_toc_row(nav), "NAV_SCRIPT": NAV_SCRIPT}
    repl.update({ph: html for ph, html in sections.values()})
    if "policy" not in empty:
        repl["POLICY_LEGEND"] = render_legend(data)
    for k, v in repl.items():
        out = out.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{[A-Z_]+\}\}", out)
    if left:
        sys.exit(f"Unreplaced placeholders: {left}")
    OUT.write_text(out, encoding="utf-8")
    skipped = f"; skipped empty: {', '.join(sorted(empty))}" if empty else ""
    print(f"Wrote {OUT} ({len(out):,} bytes){skipped}")


if __name__ == "__main__":
    main()
