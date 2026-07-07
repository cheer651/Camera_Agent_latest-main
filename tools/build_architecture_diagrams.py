from __future__ import annotations

from pathlib import Path
from textwrap import wrap

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(r"C:\Users\chens\Desktop\camera_project")
OUT_DIR = ROOT / "docs" / "diagrams"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = []
    if bold:
        candidates.extend(
            [
                r"C:\Windows\Fonts\arialbd.ttf",
                r"C:\Windows\Fonts\segoeuib.ttf",
                r"C:\Windows\Fonts\calibrib.ttf",
            ]
        )
    else:
        candidates.extend(
            [
                r"C:\Windows\Fonts\arial.ttf",
                r"C:\Windows\Fonts\segoeui.ttf",
                r"C:\Windows\Fonts\calibri.ttf",
            ]
        )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


TITLE_FONT = font(54, True)
SECTION_FONT = font(33, True)
SUBTITLE_FONT = font(27, True)
BODY_FONT = font(24, False)
SMALL_FONT = font(21, False)
TINY_FONT = font(18, False)


BG = "#ffffff"
OUTLINE = "#a7a7a7"
TEXT = "#1f1f1f"
SOFT = "#f7f7f7"
HIGHLIGHT = "#fff4c9"
ACCENT = "#f3f6fb"
ARROW = "#383838"


def rounded(draw: ImageDraw.ImageDraw, box, radius=20, fill=BG, outline=OUTLINE, width=2):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def arrow(draw: ImageDraw.ImageDraw, start, end, width=4, fill=ARROW, head=16):
    draw.line([start, end], fill=fill, width=width)
    x1, y1 = end
    x0, y0 = start
    if abs(x1 - x0) >= abs(y1 - y0):
        if x1 >= x0:
            pts = [(x1, y1), (x1 - head, y1 - head // 2), (x1 - head, y1 + head // 2)]
        else:
            pts = [(x1, y1), (x1 + head, y1 - head // 2), (x1 + head, y1 + head // 2)]
    else:
        if y1 >= y0:
            pts = [(x1, y1), (x1 - head // 2, y1 - head), (x1 + head // 2, y1 - head)]
        else:
            pts = [(x1, y1), (x1 - head // 2, y1 + head), (x1 + head // 2, y1 + head)]
    draw.polygon(pts, fill=fill)


def fit_line(draw: ImageDraw.ImageDraw, text: str, max_width: int, use_font) -> list[str]:
    if "\n" in text:
        lines = []
        for part in text.splitlines():
            lines.extend(fit_line(draw, part, max_width, use_font) if part else [""])
        return lines
    words = text.split()
    if not words:
        return [text]
    lines = []
    current = words[0]
    for word in words[1:]:
        trial = current + " " + word
        if draw.textbbox((0, 0), trial, font=use_font)[2] <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def draw_text_block(
    draw: ImageDraw.ImageDraw,
    box,
    text: str,
    use_font,
    fill=TEXT,
    align="center",
    valign="center",
    line_spacing=8,
):
    x0, y0, x1, y1 = box
    max_width = max(40, x1 - x0 - 18)
    lines = fit_line(draw, text, max_width, use_font)
    sizes = [draw.textbbox((0, 0), line or " ", font=use_font) for line in lines]
    heights = [b[3] - b[1] for b in sizes]
    total_h = sum(heights) + max(0, len(lines) - 1) * line_spacing
    if valign == "top":
        y = y0 + 8
    elif valign == "bottom":
        y = y1 - total_h - 8
    else:
        y = y0 + (y1 - y0 - total_h) / 2
    for line, bb, h in zip(lines, sizes, heights):
        line_w = bb[2] - bb[0]
        if align == "left":
            x = x0 + 10
        elif align == "right":
            x = x1 - line_w - 10
        else:
            x = x0 + (x1 - x0 - line_w) / 2
        draw.text((x, y), line, font=use_font, fill=fill)
        y += h + line_spacing


def draw_label_box(draw, box, title, subtitle=None, fill=BG, title_font=BODY_FONT, subtitle_font=SMALL_FONT):
    rounded(draw, box, radius=16, fill=fill, outline=OUTLINE, width=2)
    x0, y0, x1, y1 = box
    if subtitle:
        draw_text_block(draw, (x0 + 8, y0 + 10, x1 - 8, y0 + 48), title, title_font, valign="top")
        draw_text_block(draw, (x0 + 10, y0 + 48, x1 - 10, y1 - 8), subtitle, subtitle_font, fill="#4b4b4b")
    else:
        draw_text_block(draw, box, title, title_font)


def render_system_architecture() -> Path:
    w, h = 2200, 1400
    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)

    outer = (35, 20, w - 35, h - 20)
    rounded(draw, outer, radius=24, fill=BG, outline=OUTLINE, width=3)
    draw_text_block(draw, (0, 35, w, 110), "Overall System Architecture", TITLE_FONT)

    layer_x0, layer_x1 = 85, w - 85

    y1 = 135
    box1 = (layer_x0, y1, layer_x1, y1 + 150)
    rounded(draw, box1, radius=18, fill=SOFT, outline=OUTLINE, width=2)
    draw_text_block(draw, (box1[0] + 22, box1[1], box1[0] + 250, box1[3]), "Device Access Layer", SECTION_FONT)
    draw_label_box(draw, (470, y1 + 36, 980, y1 + 118), "Cam_01 / Cam_02", "IP Cameras", fill=BG, title_font=SUBTITLE_FONT)
    draw_label_box(draw, (1170, y1 + 36, 1660, y1 + 118), "RTSP Sub-stream", "Secondary Stream", fill=BG, title_font=SUBTITLE_FONT)

    arrow(draw, (1100, box1[3]), (1100, 350))

    y2 = 350
    box2 = (layer_x0, y2, layer_x1, y2 + 160)
    rounded(draw, box2, radius=18, fill=SOFT, outline=OUTLINE, width=2)
    draw_text_block(draw, (box2[0] + 18, box2[1], box2[0] + 250, box2[3]), "Video Processing Layer", SECTION_FONT)
    r1 = (520, y2 + 34, 910, y2 + 126)
    r2 = (980, y2 + 34, 1370, y2 + 126)
    r3 = (1440, y2 + 34, 1830, y2 + 126)
    draw_label_box(draw, r1, "Clip Recording", fill=BG, title_font=SUBTITLE_FONT)
    draw_label_box(draw, r2, "Keyframe Extraction", fill=BG, title_font=SUBTITLE_FONT)
    draw_label_box(draw, r3, "Event Merging", fill=BG, title_font=SUBTITLE_FONT)
    arrow(draw, (910, y2 + 80), (980, y2 + 80))
    arrow(draw, (1370, y2 + 80), (1440, y2 + 80))

    arrow(draw, (1100, box2[3]), (1100, 585))

    y3 = 555
    box3 = (layer_x0, y3, layer_x1, y3 + 165)
    rounded(draw, box3, radius=18, fill=HIGHLIGHT, outline=OUTLINE, width=2)
    draw_text_block(draw, (box3[0] + 18, box3[1], box3[0] + 250, box3[3]), "Intelligent Analysis Layer", SECTION_FONT)
    a1 = (520, y3 + 38, 910, y3 + 128)
    a2 = (970, y3 + 38, 1360, y3 + 128)
    a3 = (1420, y3 + 38, 1810, y3 + 128)
    draw_label_box(draw, a1, "Qwen2.5-VL", "Keyframe Analysis", fill="#fff7de", title_font=SUBTITLE_FONT, subtitle_font=BODY_FONT)
    draw_label_box(draw, a2, "Agent Orchestration", fill="#fff7de", title_font=SUBTITLE_FONT)
    draw_label_box(draw, a3, "Risk Assessment", fill="#fff7de", title_font=SUBTITLE_FONT)
    arrow(draw, (910, y3 + 83), (970, y3 + 83))
    arrow(draw, (1360, y3 + 83), (1420, y3 + 83))

    arrow(draw, (1100, box3[3]), (1100, 835))

    y4 = 770
    box4 = (540, y4, 1845, y4 + 220)
    rounded(draw, box4, radius=18, fill=ACCENT, outline=OUTLINE, width=2)
    draw_text_block(draw, (box4[0], box4[1] + 8, box4[2], box4[1] + 46), "Memory and Retrieval Layer", SECTION_FONT)

    qbox = (100, y4 + 28, 360, y4 + 180)
    draw_label_box(draw, qbox, "User Query", fill=BG, title_font=SUBTITLE_FONT)
    arrow(draw, (360, y4 + 104), (540, y4 + 104))

    m1 = (620, y4 + 72, 910, y4 + 182)
    m2 = (975, y4 + 72, 1265, y4 + 182)
    m3 = (1330, y4 + 72, 1765, y4 + 182)
    draw_label_box(draw, m1, "SQLite", "Structured Event DB", fill=BG, title_font=SUBTITLE_FONT)
    draw_label_box(draw, m2, "Qdrant", "Vector Database", fill=BG, title_font=SUBTITLE_FONT)
    draw_label_box(draw, m3, "Embedding Service", fill=BG, title_font=SUBTITLE_FONT)
    draw.text((930, y4 + 84), "Structured\nFiltering", font=TINY_FONT, fill="#4d4d4d", align="center")
    draw.text((1288, y4 + 84), "Semantic\nRanking", font=TINY_FONT, fill="#4d4d4d", align="center")
    arrow(draw, (910, y4 + 128), (975, y4 + 128))
    arrow(draw, (1265, y4 + 128), (1330, y4 + 128))

    arrow(draw, (1100, box4[3]), (1100, 1085))

    y5 = 1030
    box5 = (530, y5, 1845, y5 + 160)
    rounded(draw, box5, radius=18, fill=SOFT, outline=OUTLINE, width=2)
    draw_text_block(draw, (box5[0], box5[1] + 8, box5[2], box5[1] + 46), "Interaction and Output Layer", SECTION_FONT)
    o1 = (605, y5 + 58, 840, y5 + 130)
    o2 = (930, y5 + 58, 1165, y5 + 130)
    o3 = (1255, y5 + 58, 1490, y5 + 130)
    o4 = (1580, y5 + 58, 1815, y5 + 130)
    draw_label_box(draw, o1, "Web Front-end", "Dialogue UI", fill=BG, title_font=BODY_FONT, subtitle_font=SMALL_FONT)
    draw_label_box(draw, o2, "Chat History", fill=BG, title_font=BODY_FONT)
    draw_label_box(draw, o3, "Daily / Period Summary", fill=BG, title_font=BODY_FONT)
    draw_label_box(draw, o4, "Feishu Alerts", fill=BG, title_font=BODY_FONT)

    draw_text_block(draw, (0, 1210, w, 1260), "Closed Loop: Perception -> Memory -> Reasoning -> Action", SUBTITLE_FONT)
    foot = (
        "Core design principle: coordinated five-layer collaboration of camera acquisition, "
        "structured events, semantic retrieval, agent orchestration, and front-end interaction."
    )
    draw_text_block(draw, (95, 1270, w - 95, 1360), foot, BODY_FONT, align="left", valign="top")

    out = OUT_DIR / "overall_system_architecture_en.png"
    img.save(out)
    return out


def draw_table_like(draw, box, title, lines):
    rounded(draw, box, radius=14, fill=BG, outline=OUTLINE, width=2)
    x0, y0, x1, y1 = box
    draw_text_block(draw, (x0 + 8, y0 + 6, x1 - 8, y0 + 38), title, BODY_FONT)
    draw.line((x0, y0 + 42, x1, y0 + 42), fill=OUTLINE, width=2)
    draw_text_block(draw, (x0 + 12, y0 + 50, x1 - 12, y1 - 10), "\n".join(lines), TINY_FONT, align="left", valign="top", line_spacing=6)


def render_agent_architecture() -> Path:
    w, h = 2300, 1400
    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)

    outer = (35, 20, w - 35, h - 20)
    rounded(draw, outer, radius=24, fill=BG, outline=OUTLINE, width=3)
    draw_text_block(draw, (0, 35, w, 110), "Agent Architecture", TITLE_FONT)

    # Perception
    p = (80, 130, w - 80, 340)
    rounded(draw, p, radius=18, fill=SOFT, outline=OUTLINE, width=2)
    draw_text_block(draw, (p[0], p[1] + 6, p[2], p[1] + 44), "Perception Module", SECTION_FONT)
    in_box = (120, 190, 370, 300)
    draw_label_box(draw, in_box, "RTSP Streams /\nMP4 Clips", fill=BG, title_font=SUBTITLE_FONT)
    b1 = (480, 190, 730, 300)
    b2 = (860, 190, 1110, 300)
    b3 = (1240, 190, 1520, 300)
    b4 = (1640, 190, 2090, 300)
    draw_label_box(draw, b1, "Motion Detection", fill=BG, title_font=SUBTITLE_FONT)
    draw_label_box(draw, b2, "Peak-frame Selection", fill=BG, title_font=SUBTITLE_FONT)
    draw_label_box(draw, b3, "Background Change\nCheck", fill=BG, title_font=SUBTITLE_FONT)
    draw_label_box(draw, b4, "Event Windowing &\nDuplicate Filtering", fill=BG, title_font=SUBTITLE_FONT)
    arrow(draw, (370, 245), (480, 245))
    arrow(draw, (730, 245), (860, 245))
    arrow(draw, (1110, 245), (1240, 245))
    arrow(draw, (1520, 245), (1640, 245))
    draw_text_block(draw, (980, 305, 1550, 335), "Event window start / end time", TINY_FONT)

    arrow(draw, (1150, p[3]), (1150, 425))

    # Memory
    m = (120, 400, w - 120, 790)
    rounded(draw, m, radius=18, fill=ACCENT, outline=OUTLINE, width=2)
    draw_text_block(draw, (m[0], m[1] + 6, m[2], m[1] + 44), "Memory Module", SECTION_FONT)
    sm = (170, 465, 1230, 730)
    vm = (1330, 465, 2130, 730)
    rounded(draw, sm, radius=16, fill=BG, outline=OUTLINE, width=2)
    rounded(draw, vm, radius=16, fill=BG, outline=OUTLINE, width=2)
    draw_text_block(draw, (sm[0], sm[1] + 6, sm[2], sm[1] + 40), "Structured Memory", SUBTITLE_FONT)
    draw_text_block(draw, (vm[0], vm[1] + 6, vm[2], vm[1] + 40), "Semantic Memory", SUBTITLE_FONT)

    draw_table_like(draw, (210, 520, 460, 650), "Tasks", ["...", "...", "..."])
    draw_table_like(draw, (490, 520, 840, 650), "Recordings", ["clip_path", "frames_written", "fps", "status"])
    draw_table_like(
        draw,
        (870, 520, 1210, 650),
        "Events",
        ["description", "risk_level", "person_count", "action_type", "upper_clothing_color", "confidence"],
    )
    draw_label_box(draw, (470, 670, 950, 715), "Summaries: summaries, summary_type, ...", fill=BG, title_font=SMALL_FONT)

    v1 = (1380, 520, 1620, 575)
    v2 = (1660, 520, 1870, 575)
    v3 = (1380, 600, 1620, 655)
    v4 = (1660, 600, 1870, 655)
    v5 = (1380, 680, 1980, 730)
    v6 = (1660, 520, 2070, 730)
    draw_label_box(draw, v1, "Vectorized Event Text", fill=SOFT, title_font=SMALL_FONT)
    draw_label_box(draw, v2, "Person in Black", fill=SOFT, title_font=SMALL_FONT)
    draw_label_box(draw, v3, "Loitering?", fill=SOFT, title_font=SMALL_FONT)
    draw_label_box(draw, v4, "Similar Events", fill=SOFT, title_font=SMALL_FONT)
    draw_label_box(draw, v5, "Did a similar event occur?", fill=SOFT, title_font=SMALL_FONT)

    arrow(draw, (1210, 585), (1330, 585))
    arrow(draw, (1150, m[3]), (1150, 865))

    # Reasoning
    r = (120, 840, w - 120, 1060)
    rounded(draw, r, radius=18, fill=HIGHLIGHT, outline=OUTLINE, width=2)
    draw_text_block(draw, (r[0], r[1] + 6, r[2], r[1] + 44), "Reasoning Module", SECTION_FONT)
    rb1 = (190, 910, 760, 1015)
    rb2 = (880, 910, 1430, 1015)
    rb3 = (1550, 910, 2100, 1015)
    draw_label_box(draw, rb1, "Qwen2.5-VL Visual Analysis", "Keyframe semantic interpretation", fill="#fff7de", title_font=SUBTITLE_FONT, subtitle_font=SMALL_FONT)
    draw_label_box(draw, rb2, "Qwen2.5 Text Reasoning", "QA and summarization", fill="#fff7de", title_font=SUBTITLE_FONT, subtitle_font=SMALL_FONT)
    draw_label_box(draw, rb3, "Retrieval & Aggregation Logic", "Constraint parsing + retrieval + aggregation", fill="#fff7de", title_font=SUBTITLE_FONT, subtitle_font=SMALL_FONT)
    arrow(draw, (760, 962), (880, 962))
    arrow(draw, (1430, 962), (1550, 962))

    arrow(draw, (1150, r[3]), (1150, 1155))

    # Action
    a = (140, 1115, w - 140, 1290)
    rounded(draw, a, radius=18, fill=SOFT, outline=OUTLINE, width=2)
    draw_text_block(draw, (a[0] + 18, a[1], a[0] + 260, a[3]), "Action Module", SECTION_FONT)
    ab1 = (430, 1160, 830, 1260)
    ab2 = (980, 1160, 1450, 1260)
    ab3 = (1600, 1160, 2060, 1260)
    draw_label_box(draw, ab1, "SQLite / Qdrant Write-back", fill=BG, title_font=SUBTITLE_FONT)
    draw_label_box(draw, ab2, "Feishu Alerts", "Notification messages + snapshots", fill=BG, title_font=SUBTITLE_FONT, subtitle_font=SMALL_FONT)
    draw_label_box(draw, ab3, "Daily Summaries", "Time-period summaries + daily report", fill=BG, title_font=SUBTITLE_FONT, subtitle_font=SMALL_FONT)

    footer = "The core of the agent is not one-shot generation, but a closed loop of Perception -> Memory -> Reasoning -> Action."
    draw_text_block(draw, (80, 1310, w - 80, 1370), footer, BODY_FONT)

    out = OUT_DIR / "agent_architecture_en.png"
    img.save(out)
    return out


def main():
    overall = render_system_architecture()
    agent = render_agent_architecture()
    print(overall)
    print(agent)


if __name__ == "__main__":
    main()
