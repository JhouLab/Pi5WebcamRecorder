import os
import re
import shutil
import tempfile


def update_config_option(config_path, key, value, section='options'):
    """
    Sets "key = value" in a config file, changing only that one line.

    Unlike configparser, which discards all comments when it saves, this edits the text directly,
    so every comment, blank line and other option in the file is left exactly as it was.

    - If an active (not commented-out) line for the key exists, that line is replaced.
    - Otherwise a new line is added at the end of the given [section].
    - The file is replaced atomically, so a crash or power loss can't leave a half-written config.

    Raises an exception if the file can't be read or written, or if it has no such section.
    """
    with open(config_path, 'r', newline='') as f:
        text = f.read()

    newline = '\r\n' if text.count('\r\n') > text.count('\n') / 2 else '\n'
    lines = text.splitlines(keepends=True)
    new_body = f"{key} = {value}"

    key_pattern = re.compile(r'^\s*' + re.escape(key) + r'\s*[=:]', re.IGNORECASE)
    section_pattern = re.compile(r'^\s*\[\s*' + re.escape(section) + r'\s*\]\s*$', re.IGNORECASE)
    any_section_pattern = re.compile(r'^\s*\[.*\]\s*$')

    # Find the section boundaries
    start = None
    end = len(lines)
    for i, line in enumerate(lines):
        if start is None:
            if section_pattern.match(line):
                start = i + 1
        elif any_section_pattern.match(line):
            end = i
            break

    if start is None:
        raise ValueError(f"Config file '{config_path}' has no [{section}] section.")

    replaced = False
    for i in range(start, end):
        if key_pattern.match(lines[i]):
            stripped = lines[i].rstrip('\r\n')
            ending = lines[i][len(stripped):] or newline
            lines[i] = new_body + ending
            replaced = True
            break

    if not replaced:
        # Insert after the last non-blank line of the section
        insert_at = start
        for i in range(start, end):
            if lines[i].strip() != '':
                insert_at = i + 1
        if insert_at > 0 and not lines[insert_at - 1].endswith(('\n', '\r')):
            lines[insert_at - 1] += newline
        lines.insert(insert_at, new_body + newline)

    # Write to a temporary file in the same folder, then atomically replace the original
    folder = os.path.dirname(os.path.abspath(config_path))
    fd, tmp_path = tempfile.mkstemp(dir=folder, prefix='.config_tmp_')
    try:
        with os.fdopen(fd, 'w', newline='') as f:
            f.writelines(lines)
            f.flush()
            os.fsync(f.fileno())
        try:
            # Preserve permissions and owner (the program may be running as root)
            shutil.copymode(config_path, tmp_path)
            st = os.stat(config_path)
            os.chown(tmp_path, st.st_uid, st.st_gid)
        except Exception:
            pass
        os.replace(tmp_path, config_path)
    except Exception:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        raise
