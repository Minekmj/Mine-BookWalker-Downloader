import re
from typing import List


def parse_api_keys(raw: str) -> List[str]:
    parts = re.split(r"[\r\n,;]+", raw or "")
    keys: List[str] = []
    seen = set()
    for p in parts:
        k = p.strip()
        if k and k not in seen:
            seen.add(k)
            keys.append(k)
    return keys


def list_gemini_models(api_key: str) -> List[str]:
    from google import genai

    client = genai.Client(api_key=api_key.strip())
    names: List[str] = []
    for m in client.models.list():
        name = getattr(m, "name", "") or ""
        if name.startswith("models/"):
            name = name[len("models/"):]
        if "gemini" not in name.lower():
            continue
        methods = getattr(m, "supported_actions", None) or getattr(m, "supported_generation_methods", None) or []
        if methods and not any("generateContent" in str(act) for act in methods):
            continue
        names.append(name)
    return sorted(set(names))
