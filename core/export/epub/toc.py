from typing import Dict

from core.export.epub.text_utils import _plain_key, _toc_text, _xml_safe
from core.ocr import TextSpan


def find_toc_target(text: str, title_targets: Dict[str, str]) -> str:
    key = _plain_key(_toc_text([TextSpan(text)]))
    if not key:
        return ""
    exact = title_targets.get(key)
    if exact:
        return exact
    candidates = [(len(title_key), href) for title_key, href in title_targets.items() if len(title_key) >= 2 and (key.startswith(title_key) or title_key.startswith(key))]
    return max(candidates, default=(0, ""))[1]


def section_tree(sections):
    roots = []
    stack = [(1, roots)]
    for level, section_id, title in sections:
        level = max(2, min(3, int(level)))
        while stack and stack[-1][0] >= level:
            stack.pop()
        if not stack:
            stack = [(1, roots)]
        node = {"id": section_id, "title": title, "children": []}
        stack[-1][1].append(node)
        stack.append((level, node["children"]))
    return roots


def render_nav_sections(sections, filename):
    tree = section_tree(sections)

    def render(nodes):
        rows = ["<ol>"]
        for node in nodes:
            rows.append(f'<li><a href="{filename}#{node["id"]}">{_xml_safe(node["title"])}</a>')
            if node["children"]:
                rows.append(render(node["children"]))
            rows.append("</li>")
        rows.append("</ol>")
        return "".join(rows)

    return render(tree) if tree else ""
