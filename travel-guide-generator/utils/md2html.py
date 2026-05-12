"""Convert markdown to mobile-friendly HTML."""
import re


def escape_html(text):
    text = text.replace("&", "&amp;")
    text = text.replace("("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def parse_inline(text):
    text = re.sub(r"\*\*(.+?)\*\*", r""<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r""<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r""<code>\1</code>", text)
    return text


def markdown_to_html(md_text):
    lines = md_text.split("\n")
    html_parts = []
    i = 0
    in_code_block = False
    code_lines = []
    in_table = False
    table_rows = []
    in_blockquote = False
    bq_lines = []
    in_list = False
    list_items = []
    list_type = None

    def flush_list():
        nonlocal in_list, list_items, list_type
        if not in_list:
            return
        tag = "ol" if list_type == "ol" else "ul"
        html_parts.append(f"<{tag}>")
        for item in list_items:
            html_parts.append(f""<li>{item}</li>")
        html_parts.append(f"</{tag}>")
        in_list = False
        list_items = []
        list_type = None

    def flush_table():
        nonlocal in_table, table_rows
        if not in_table or len(table_rows) < 2:
            in_table = False
            table_rows = []
            return
        html_parts.append('<div class="table-wrap"><table>')
        headers = [c.strip() for c in table_rows[0].split("|")]
        headers = [h for h in headers if h]
        html_parts.append("("<thead><tr>")
        for h in headers:
            html_parts.append(f""<th>{parse_inline(escape_html(h))}</th>")
        html_parts.append("</tr></thead>")
        html_parts.append("("<tbody>")
        for row in table_rows[2:]:
            cells = [c.strip() for c in row.split("|")]
            cells = [c for c in cells if c or c == ""]
            if row.startswith("|"):
                cells = cells[1:] if cells and cells[0] == "" else cells
            html_parts.append("("<tr>")
            for c in cells[:len(headers)]:
                html_parts.append(f""<td>{parse_inline(escape_html(c))}</td>")
            html_parts.append("</tr>")
        html_parts.append("</tbody></table></div>")
        in_table = False
        table_rows = []

    def flush_bq():
        nonlocal in_blockquote, bq_lines
        if not in_blockquote:
            return
        html_parts.append("("<blockquote>")
        inner = " "<br>".join(bq_lines)
        inner = parse_inline(escape_html(inner))
        html_parts.append(inner)
        html_parts.append("</blockquote>")
        in_blockquote = False
        bq_lines = []

    while i < len(lines):
        line = lines[i]

        if line.startswith("```"):
            if not in_code_block:
                in_code_block = True
                flush_list()
                flush_table()
                flush_bq()
                code_lines = []
            else:
                in_code_block = False
                code = escape_html("\n".join(code_lines))
                html_parts.append(f""<pre><code>{code}</code></pre>")
            i += 1
            continue

        if in_code_block:
            code_lines.append(line)
            i += 1
            continue

        if line.startswith("> "):
            flush_list()
            flush_table()
            if not in_blockquote:
                in_blockquote = True
                bq_lines = []
            bq_lines.append(line[2:])
            i += 1
            continue
        else:
            flush_bq()

        if line.strip().startswith("|") and line.strip().endswith("|"):
            flush_list()
            if not in_table:
                in_table = True
                table_rows = []
            table_rows.append(line.strip())
            i += 1
            continue
        else:
            flush_table()

        if line.strip() == "":
            flush_list()
            i += 1
            continue

        if line.strip() == "---":
            flush_list()
            html_parts.append("("<hr>")
            i += 1
            continue

        if line.startswith("# "):
            flush_list()
            html_parts.append(f""<h1>{parse_inline(escape_html(line[2:]))}</h1>")
            i += 1
            continue
        if line.startswith("## "):
            flush_list()
            html_parts.append(f""<h2>{parse_inline(escape_html(line[3:]))}</h2>")
            i += 1
            continue
        if line.startswith("### "):
            flush_list()
            html_parts.append(f""<h3>{parse_inline(escape_html(line[4:]))}</h3>")
            i += 1
            continue
        if line.startswith("#### "):
            flush_list()
            html_parts.append(f""<h4>{parse_inline(escape_html(line[5:]))}</h4>")
            i += 1
            continue

        if re.match(r"^\s*[-*+]\s+", line):
            if not in_list or list_type != "ul":
                flush_list()
                in_list = True
                list_type = "ul"
            item_text = re.sub(r"^\s*[-*+]\s+", "", line)
            list_items.append(parse_inline(escape_html(item_text)))
            i += 1
            continue
        if re.match(r"^\s*\d+\.\s+", line):
            if not in_list or list_type != "ol":
                flush_list()
                in_list = True
                list_type = "ol"
            item_text = re.sub(r"^\s*\d+\.\s+", "", line)
            list_items.append(parse_inline(escape_html(item_text)))
            i += 1
            continue

        flush_list()
        html_parts.append(f"""<p>{parse_inline(escape_html(line))}</p>")
        i += 1

    flush_list()
    flush_table()
    flush_bq()

    return "\n".join(html_parts)


def wrap_html(body_html, title="Travel Guide"):
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>{title}</title>
<style>
  :root {{ --bg: #f7f8fa; --card: #ffffff; --text: #1a1a2e; --muted: #555; --accent: #e63946; --accent2: #2a9d8f; --border: #e1e4e8; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 16px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif; background: var(--bg); color: var(--text); line-height: 1.75; font-size: 15px; }}
  h1 {{ font-size: 24px; margin: 24px 0 12px; padding-bottom: 8px; border-bottom: 3px solid var(--accent); color: var(--accent); }}
  h2 {{ font-size: 20px; margin: 28px 0 12px; padding-left: 10px; border-left: 4px solid var(--accent2); color: var(--text); }}
  h3 {{ font-size: 17px; margin: 20px 0 8px; color: #333; }}
  h4 {{ font-size: 15px; margin: 16px 0 6px; color: #444; }}
  p {{ margin: 10px 0; }}
  blockquote {{ margin: 12px 0; padding: 12px 16px; background: #fff3cd; border-left: 4px solid #ffc107; border-radius: 4px; color: #664d03; font-size: 14px; }}
  ul, ol {{ margin: 10px 0; padding-left: 22px; }}
  li {{ margin: 6px 0; }}
  hr {{ border: none; border-top: 1px dashed var(--border); margin: 24px 0; }}
  code {{ background: #f0f0f0; padding: 2px 5px; border-radius: 3px; font-size: 13px; font-family: "SF Mono", Monaco, monospace; }}
  pre {{ background: #1e1e2e; color: #cdd6f4; padding: 14px; border-radius: 8px; overflow-x: auto; font-size: 13px; }}
  pre code {{ background: transparent; padding: 0; }}
  strong {{ color: var(--accent); }}
  .table-wrap {{ overflow-x: auto; margin: 12px 0; border-radius: 8px; border: 1px solid var(--border); background: var(--card); }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; min-width: 600px; }}
  th, td {{ padding: 8px 10px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }}
  th {{ background: #fafafa; font-weight: 600; position: sticky; top: 0; }}
  tr:last-child td {{ border-bottom: none; }}
</style>
</head>
<body>
{body_html}
</body>
</html>"""
