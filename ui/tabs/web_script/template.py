from path_clean import resource_path

SCRIPT_PATH = resource_path("ui", "tabs", "web_script", "js", "web_script.js")


def render_web_script(*, dpr: int, idle_ms: int, min_wait_ms: int, start_page: int, port: int) -> str:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    values = {"DPR": dpr, "IDLE_MS": idle_ms, "MIN_WAIT_MS": min_wait_ms, "START_PAGE": max(1, int(start_page)), "SERVER_PORT": port, "TARGET": 'url.includes("bw-bv-epubs.bookwalker.jp") || url.includes(".jpeg") || url.includes(".jpg") || url.includes(".json")'}
    for key, value in values.items():
        source = source.replace(f"@@{key}@@", str(value))
    return source
