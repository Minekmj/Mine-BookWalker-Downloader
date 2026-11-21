from dataclasses import dataclass

@dataclass
class EpubDesignConfig:
    writing_mode: str = "horizontal"
    theme: str = "default"
    font_family: str = "serif"
    font_size_pct: int = 100
    line_height: float = 1.85
    text_indent_em: float = 1.0
    no_indent_dialogue: bool = True
    para_margin_em: float = 0.30
    body_margin_em: float = 1.2
    heading_style: str = "underline"
    scene_break_style: str = "stars"
    chapter_page_break: bool = True
    illust_page_break: bool = True
    cover_enabled: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> "EpubDesignConfig":
        return cls(
            writing_mode=str(d.get("epub_writing_mode", "horizontal")),
            theme=str(d.get("epub_theme", "default")),
            font_family=str(d.get("epub_font_family", "serif")),
            font_size_pct=int(d.get("epub_font_size_pct", 100)),
            line_height=float(d.get("epub_line_height", 1.85)),
            text_indent_em=float(d.get("epub_text_indent_em", 1.0)),
            no_indent_dialogue=bool(d.get("epub_no_indent_dialogue", True)),
            para_margin_em=float(d.get("epub_para_margin_em", 0.30)),
            body_margin_em=float(d.get("epub_body_margin_em", 1.2)),
            heading_style=str(d.get("epub_heading_style", "underline")),
            scene_break_style=str(d.get("scene_break_style", "stars")),
            chapter_page_break=bool(d.get("epub_chapter_page_break", True)),
            illust_page_break=bool(d.get("epub_illust_page_break", True)),
            cover_enabled=bool(d.get("epub_cover_enabled", True)),
        )

def generate_epub_css(cfg: EpubDesignConfig) -> str:
    wm_css = ""
    if cfg.writing_mode == "vertical":
        wm_css = (
            "html {\n"
            "  writing-mode: vertical-rl;\n"
            "  -webkit-writing-mode: vertical-rl;\n"
            "  -epub-writing-mode: vertical-rl;\n"
            "}\n"
        )

    if cfg.font_family == "serif":
        font_css = '"Hiragino Mincho ProN", "Yu Mincho", "Noto Serif CJK JP", "Noto Serif KR", "Batang", serif'
    elif cfg.font_family == "sans":
        font_css = '"Hiragino Kaku Gothic ProN", "Yu Gothic", "Noto Sans CJK JP", "Noto Sans KR", "Malgun Gothic", sans-serif'
    else:
        font_css = "inherit"

    theme_css = ""
    border_col = "#9ca3af"
    if cfg.theme == "light":
        theme_css = "  background-color: #ffffff;\n  color: #1a1a1a;\n"
        border_col = "#9ca3af"
    elif cfg.theme == "sepia":
        theme_css = "  background-color: #f7f1e3;\n  color: #2c241b;\n"
        border_col = "#b8a68e"
    elif cfg.theme == "dark":
        theme_css = "  background-color: #181a1f;\n  color: #d6d9e0;\n"
        border_col = "#4b5563"

    chap_break = "  page-break-before: always;\n" if cfg.chapter_page_break else ""
    if cfg.heading_style == "centered":
        heading_css = (
            "h1.chapter-title {\n"
            f"{chap_break}"
            "  font-size: 1.45em;\n"
            "  font-weight: bold;\n"
            "  text-align: center;\n"
            "  margin: 1.8em 0 1.6em 0;\n"
            "}\n"
        )
    elif cfg.heading_style == "simple":
        heading_css = (
            "h1.chapter-title {\n"
            f"{chap_break}"
            "  font-size: 1.4em;\n"
            "  font-weight: bold;\n"
            "  margin: 1.4em 0 1.2em 0;\n"
            "}\n"
        )
    else:
        heading_css = (
            "h1.chapter-title {\n"
            f"{chap_break}"
            "  font-size: 1.45em;\n"
            "  font-weight: bold;\n"
            "  margin: 1.2em 0 1.4em 0;\n"
            "  padding-bottom: 0.45em;\n"
            f"  border-bottom: 1px solid {border_col};\n"
            "}\n"
        )

    dialogue_css = "p.dialogue { text-indent: 0; }\n" if cfg.no_indent_dialogue else ""
    illust_break = "  page-break-after: always;\n" if cfg.illust_page_break else ""

    return (
        f"{wm_css}"
        "body {\n"
        f"{theme_css}"
        f"  font-family: {font_css};\n"
        f"  font-size: {cfg.font_size_pct}%;\n"
        f"  line-height: {cfg.line_height:.2f};\n"
        f"  margin: {cfg.body_margin_em:.2f}em;\n"
        "}\n"
        "body.cover-page { margin: 0; padding: 0; text-align: center; }\n"
        ".cover-wrap { text-align: center; page-break-after: always; }\n"
        ".cover-wrap img { max-width: 100%; max-height: 98vh; width: auto; height: auto; }\n"
        f"{heading_css}"
        "h2.section-title { font-size: 1.18em; font-weight: bold; margin: 1.5em 0 0.8em 0; }\n"
        "h3.section-title { font-size: 1.05em; font-weight: bold; margin: 1.2em 0 0.6em 0; }\n"
        "p {\n"
        f"  margin: {cfg.para_margin_em:.2f}em 0;\n"
        f"  text-indent: {cfg.text_indent_em:.2f}em;\n"
        "}\n"
        f"{dialogue_css}"
        "strong, b { font-weight: bold; }\n"
        ".scene-break { text-align: center; margin: 1.6em 0; letter-spacing: 0.35em; text-indent: 0; }\n"
        f"hr.scene-hr {{ border: none; border-top: 1px solid {border_col}; width: 40%; margin: 1.6em auto; }}\n"
        ".illust-wrap {\n"
        "  text-align: center;\n"
        "  margin: 1em 0;\n"
        "  page-break-inside: avoid;\n"
        f"{illust_break}"
        "}\n"
        ".illust-wrap img { max-width: 100%; max-height: 94vh; width: auto; height: auto; }\n"
        ".illust-wrap.inline-illust { margin: 0.65em auto; page-break-inside: avoid; page-break-after: auto; }\n"
        ".illust-wrap.inline-illust img { max-height: 68vh; }\n"
    )
