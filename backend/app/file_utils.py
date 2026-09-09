def _file_marker(line: str):
    """Return the filename from a file marker, or None.

    Supports both `// FILE: Name.ext` (Java/JS) and `# FILE: path/name.ext`
    (Python) so stack-aware generators can emit idiomatic comments.
    """
    stripped = line.strip()
    for prefix in ("// FILE:", "# FILE:"):
        if stripped.startswith(prefix):
            return stripped.split(prefix, 1)[1].strip()
    return None


def parse_files(code_text: str) -> dict:
    files = {}
    current_name = None
    current_lines = []

    for line in (code_text or "").splitlines():
        marker = _file_marker(line)
        if marker:
            if current_name:
                files[current_name] = "\n".join(current_lines).strip()
            current_name = marker
            current_lines = []
        else:
            current_lines.append(line)

    if current_name:
        files[current_name] = "\n".join(current_lines).strip()

    if not files and (code_text or "").strip():
        files["Main.java"] = code_text.strip()

    return files