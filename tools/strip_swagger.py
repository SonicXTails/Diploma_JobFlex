"""
Strips @swagger_auto_schema decorators down to just (method/methods, operation_summary, tags).
Keeps all other code intact. Run from the project root.
Usage: python tools/strip_swagger.py
"""
import re
from pathlib import Path


def find_matching_paren(text: str, open_pos: int) -> int:
    """Return index AFTER the matching ')' given position of '('."""
    depth = 1
    i = open_pos + 1
    in_str = False
    str_char = ''
    while i < len(text) and depth > 0:
        ch = text[i]
        if in_str:
            if ch == '\\':
                i += 2
                continue
            if ch == str_char:
                in_str = False
        else:
            if ch in ('"', "'"):
                in_str = True
                str_char = ch
                # Handle triple-quotes
                if text[i:i+3] in ('"""', "'''"):
                    triple = text[i:i+3]
                    i += 3
                    end = text.find(triple, i)
                    if end == -1:
                        break
                    i = end + 3
                    continue
            elif ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
        i += 1
    return i


def extract_str_value(text: str, key: str):
    """Extract a single-quoted or double-quoted string value for a key."""
    pattern = rf'(?<!\w){re.escape(key)}\s*=\s*(?:u?["\'])([^"\']*)["\']'
    m = re.search(pattern, text)
    if m:
        return m.group(1)

    # Try triple-quoted
    pattern3 = rf'(?<!\w){re.escape(key)}\s*=\s*(?:u?["\']{{3}})(.*?)["\']{{3}}'
    m3 = re.search(pattern3, text, re.DOTALL)
    if m3:
        # Flatten multi-line / concatenated strings
        raw = m3.group(1)
        raw = re.sub(r'\s*["\'][\s\n]+["\']?\s*', ' ', raw)
        return raw.strip()

    # Try parenthesized concatenated string: (  "part1" "part2" ... )
    paren_pattern = rf'(?<!\w){re.escape(key)}\s*=\s*\(\s*((?:["\'][^"\']*["\'][,\s]*)+)\)'
    mp = re.search(paren_pattern, text, re.DOTALL)
    if mp:
        raw = mp.group(1)
        parts = re.findall(r'["\']([^"\']*)["\']', raw)
        return ' '.join(p.strip() for p in parts).strip()

    return None


def extract_list_value(text: str, key: str):
    """Extract a list literal value like tags=['accounts']."""
    pattern = rf'(?<!\w){re.escape(key)}\s*=\s*(\[[^\]]*\])'
    m = re.search(pattern, text)
    if m:
        # Compact spaces inside the list
        inner = re.sub(r'\s+', '', m.group(1))
        return inner
    return None


def strip_one_decorator(dec_text: str) -> str:
    """Convert a full @swagger_auto_schema(...) block to minimal form."""
    # Find method= or methods= value
    method_m = re.search(r'\bmethod\s*=\s*(["\'][^"\']+["\'])', dec_text)
    methods_m = re.search(r'\bmethods\s*=\s*(\[[^\]]*\])', dec_text)

    summary = extract_str_value(dec_text, 'operation_summary')
    tags = extract_list_value(dec_text, 'tags')

    parts = []
    if method_m:
        parts.append(f'method={method_m.group(1)}')
    elif methods_m:
        val = re.sub(r'\s+', '', methods_m.group(1))
        parts.append(f'methods={val}')

    if summary:
        escaped = summary.replace('"', '\\"')
        parts.append(f'operation_summary="{escaped}"')

    if tags:
        parts.append(f'tags={tags}')

    return '@swagger_auto_schema(' + ', '.join(parts) + ')'


def strip_swagger_in_file(filepath: str):
    path = Path(filepath)
    text = path.read_text(encoding='utf-8')
    original_lines = text.count('\n')

    result_parts = []
    pos = 0

    while True:
        idx = text.find('@swagger_auto_schema', pos)
        if idx == -1:
            result_parts.append(text[pos:])
            break

        # Include text before decorator
        result_parts.append(text[pos:idx])

        # Find the opening '('
        paren_pos = text.index('(', idx)

        # Find the matching ')'
        end_pos = find_matching_paren(text, paren_pos)

        dec_text = text[idx:end_pos]
        mini = strip_one_decorator(dec_text)
        result_parts.append(mini)

        pos = end_pos

    new_text = ''.join(result_parts)

    # Remove unused _preset_schema variable (only present in accounts/views.py)
    new_text = re.sub(
        r'\n_preset_schema\s*=\s*openapi\.Schema\([^)]*(?:\([^)]*\)[^)]*)*\)\s*\n',
        '\n',
        new_text,
        flags=re.DOTALL,
    )

    new_lines = new_text.count('\n')
    path.write_text(new_text, encoding='utf-8')
    print(f'{filepath}: {original_lines} -> {new_lines} lines  (saved {original_lines - new_lines})')


if __name__ == '__main__':
    base = Path(__file__).parent.parent
    strip_swagger_in_file(str(base / 'accounts' / 'views.py'))
    strip_swagger_in_file(str(base / 'vacancies' / 'views.py'))
    print('Done.')
