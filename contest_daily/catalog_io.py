"""Offline, conservative imports of an institution's own competition list.

Importing is deliberately separate from adopting a catalog. Every import is a
review draft, including a JSON prepared by an agent. No model, network request,
macro, embedded link, or formula is executed here.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import posixpath
import re
import tempfile
import unicodedata
import zipfile
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

MAX_SOURCE_BYTES = 15 * 1024 * 1024
MAX_EXTRACTED_CHARS = 4 * 1024 * 1024
MAX_ZIP_BYTES = 64 * 1024 * 1024
MAX_RECORDS = 2000
SUPPORTED_FORMATS = ("json", "csv", "xlsx", "docx", "pdf", "md", "txt")

_ALIASES = {
    "id": {"id", "序号", "编号", "赛事编号"},
    "name": {"name", "competition", "competitionname", "竞赛名称", "赛事名称", "比赛名称", "项目名称", "竞赛项目"},
    "suggested_level": {"suggested_level", "level", "级别", "等级", "竞赛等级", "竞赛级别", "认定等级", "认可等级", "建议等级", "分类"},
    "official_urls": {"official_urls", "official_url", "url", "官网", "官方网站", "官网链接", "赛事官网"},
}


def _header(value: str) -> str:
    return re.sub(r"[\s\-（）():：]", "", unicodedata.normalize("NFKC", str(value))).casefold()


_HEADERS = {_header(alias): field for field, aliases in _ALIASES.items() for alias in aliases}


def _clean(value) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", str(value or "")).strip()


def _url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 2048 or re.search(r"[\x00-\x20\x7f]", value):
        raise ValueError("官网链接必须是无空白字符的 HTTP(S) 链接")
    parts = urlsplit(value)
    try:
        valid = parts.scheme in {"http", "https"} and bool(parts.hostname) and not parts.username and not parts.password
        parts.port
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("官网链接必须是 HTTP(S) 链接，且不能含账号密码")
    return value


def validate_catalog(document: dict | list) -> list[dict]:
    """Return normalized records, or raise; this never confirms a catalog.

    Accepts the portable ``{"records": [...]}`` format or a bare JSON array.
    Unknown keys are excluded so source documents cannot configure the runtime.
    Names and level labels are retained verbatim except surrounding whitespace.
    """
    rows = document.get("records") if isinstance(document, dict) else document
    if not isinstance(rows, list) or not rows or len(rows) > MAX_RECORDS:
        raise ValueError(f"records 必须是包含 1 至 {MAX_RECORDS} 条赛事记录的列表")
    records, used_ids = [], set()
    for number, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f"第 {number} 条赛事必须是对象")
        identifier = row.get("id", number)
        if type(identifier) is not int or identifier < 1 or identifier in used_ids:
            raise ValueError(f"第 {number} 条赛事的 id 必须是唯一的正整数")
        name, level = row.get("name"), row.get("suggested_level", "")
        if not isinstance(name, str) or not name.strip() or len(name) > 300 or re.search(r"[\x00-\x1f\x7f]", name):
            raise ValueError(f"第 {number} 条赛事缺少有效名称（最长 300 字符）")
        if not isinstance(level, str) or len(level) > 100 or re.search(r"[\x00-\x1f\x7f]", level):
            raise ValueError(f"第 {number} 条赛事的 suggested_level 必须是简短字符串")
        urls = row.get("official_urls", [])
        if not isinstance(urls, list) or len(urls) > 10:
            raise ValueError(f"第 {number} 条赛事的 official_urls 必须是链接列表（最多 10 条）")
        record = {"id": identifier, "name": name.strip(), "suggested_level": level.strip() or "未分级", "requires_confirmation": bool(row.get("requires_confirmation", True))}
        if urls:
            record["official_urls"] = list(dict.fromkeys(_url(value) for value in urls))
        location = row.get("source_location")
        if isinstance(location, str) and len(location) <= 200:
            record["source_location"] = location
        records.append(record)
        used_ids.add(identifier)
    groups = {}
    for record in records:
        key = re.sub(r"\s+", "", unicodedata.normalize("NFKC", record["name"]))
        groups.setdefault(key, []).append(record)
    for group in groups.values():
        if len(group) > 1:
            ids = [record["id"] for record in group]
            for record in group:
                record["duplicate_group"] = ids
    return records


def _decode(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("文本编码无法识别，请另存为 UTF-8 后导入")


def _xml(payload: bytes):
    # Reject DTD/entity input rather than relying on parser-specific behavior.
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", payload.replace(b"\x00", b""), re.I):
        raise ValueError("文档 XML 含不受支持的 DTD 或实体声明")
    try:
        return ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError("文档 XML 不完整或损坏") from exc


def _archive(payload: bytes) -> zipfile.ZipFile:
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ValueError("Office 文档压缩包损坏") from exc
    members = archive.infolist()
    if len(members) > 2000 or sum(member.file_size for member in members) > MAX_ZIP_BYTES:
        archive.close()
        raise ValueError("Office 文档解压体积过大")
    if any(member.flag_bits & 1 or member.file_size > MAX_ZIP_BYTES or ".." in member.filename.split("/") or member.filename.startswith(("/", "\\")) for member in members):
        archive.close()
        raise ValueError("Office 文档包含加密内容或不安全的文件路径")
    return archive


def _read_xml(archive: zipfile.ZipFile, member: str):
    try:
        return _xml(archive.read(member))
    except KeyError as exc:
        raise ValueError(f"Office 文档缺少 {member}") from exc


def _table_records(rows: list[list[str]], location: str, warnings: list[str]) -> list[dict]:
    """Only columns with explicit headers establish a field's meaning."""
    header_index, columns = None, {}
    for index, row in enumerate(rows[:30]):
        mapped = {cell_index: _HEADERS[_header(cell)] for cell_index, cell in enumerate(row) if _header(cell) in _HEADERS}
        if "name" in mapped.values():
            if len(set(mapped.values())) != len(mapped):
                raise ValueError(f"{location} 的表头有重复字段，请先整理")
            header_index, columns = index, mapped
            break
    if header_index is None:
        warnings.append(f"{location} 未识别到明确的赛事名称表头；表格保存在提取文本中，请核对后整理 JSON。")
        return []
    records = []
    for row_number, row in enumerate(rows[header_index + 1:], header_index + 2):
        if not any(_clean(cell) for cell in row):
            continue
        values = {field: _clean(row[index]) if index < len(row) else "" for index, field in columns.items()}
        if _header(values.get("name", "")) in _ALIASES["name"]:
            continue
        if not values.get("name"):
            warnings.append(f"{location} 第 {row_number} 行缺少赛事名称，未作为记录导入；请查看提取文本。")
            continue
        # Markdown's separator row is formatting, not a competition.
        if re.fullmatch(r"[:\-\s]+", values["name"]):
            continue
        raw_id = values.get("id", "")
        if raw_id and not re.fullmatch(r"[1-9]\d*", raw_id):
            warnings.append(f"{location} 第 {row_number} 行编号不是正整数，使用新的顺序编号；原编号为 {raw_id[:60]}。")
            raw_id = ""
        record = {"name": values["name"], "suggested_level": values.get("suggested_level", ""), "source_location": f"{location}:row-{row_number}"}
        if raw_id:
            record["id"] = int(raw_id)
        if values.get("official_urls"):
            record["official_urls"] = [value for value in re.split(r"[\s,，;；]+", values["official_urls"]) if value]
        records.append(record)
        if len(records) > MAX_RECORDS:
            raise ValueError(f"赛事记录超过 {MAX_RECORDS} 条")
    return records


def _xlsx(payload: bytes, warnings: list[str]):
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    records, lines = [], []
    with _archive(payload) as archive:
        workbook = _read_xml(archive, "xl/workbook.xml")
        relationships = _read_xml(archive, "xl/_rels/workbook.xml.rels")
        targets = {rel.get("Id"): rel for rel in relationships}
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            for item in _read_xml(archive, "xl/sharedStrings.xml").findall("s:si", ns):
                shared.append("".join(node.text or "" for node in item.findall(".//s:t", ns)))
        for sheet in workbook.findall("s:sheets/s:sheet", ns):
            name = sheet.get("name", "sheet")
            relation = targets.get(sheet.get(f"{{{ns['r']}}}id"))
            if relation is None or relation.get("TargetMode") == "External":
                raise ValueError("工作表引用缺失或指向外部地址")
            target = relation.get("Target", "")
            member = posixpath.normpath(posixpath.join("xl", target)) if not target.startswith("/") else target.lstrip("/")
            if not member.startswith("xl/") or ".." in member.split("/"):
                raise ValueError("工作表路径越界")
            rows = []
            for row in _read_xml(archive, member).findall("s:sheetData/s:row", ns):
                values = {}
                for cell in row.findall("s:c", ns):
                    match = re.fullmatch(r"([A-Z]+)\d+", cell.get("r", ""))
                    if not match:
                        raise ValueError("工作表单元格引用无效")
                    column = 0
                    for letter in match.group(1):
                        column = column * 26 + ord(letter) - ord("A") + 1
                    if column > 200:
                        raise ValueError("工作表列数超过导入上限 200")
                    value = cell.findtext("s:v", default="", namespaces=ns)
                    if cell.get("t") == "s":
                        try:
                            shared_index = int(value)
                            if shared_index < 0:
                                raise ValueError
                            value = shared[shared_index]
                        except (ValueError, IndexError) as exc:
                            raise ValueError("共享字符串引用无效") from exc
                    elif cell.get("t") == "inlineStr":
                        value = "".join(node.text or "" for node in cell.findall("s:is//s:t", ns))
                    if cell.find("s:f", ns) is not None:
                        warnings.append(f"工作表 {name} 含公式，只读取文件已有的缓存值，不计算公式。")
                    values[column - 1] = value
                rows.append([values.get(index, "") for index in range(max(values, default=-1) + 1)])
                if len(rows) > MAX_RECORDS + 30:
                    raise ValueError("工作表行数超过导入上限")
            lines.extend([f"[工作表 {name}]", *("\t".join(row) for row in rows)])
            records.extend(_table_records(rows, f"sheet-{name}", warnings))
    return records, "\n".join(lines)


def _docx(payload: bytes, warnings: list[str]):
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with _archive(payload) as archive:
        document = _read_xml(archive, "word/document.xml")
    lines = ["".join(node.text or "" for node in paragraph.findall(".//w:t", ns)) for paragraph in document.findall(".//w:p", ns)]
    records = []
    for number, table in enumerate(document.findall(".//w:tbl", ns), 1):
        rows = [[" ".join("".join(node.text or "" for node in paragraph.findall(".//w:t", ns)) for paragraph in cell.findall("w:p", ns)) for cell in row.findall("w:tc", ns)] for row in table.findall("w:tr", ns)]
        records.extend(_table_records(rows, f"table-{number}", warnings))
    text = "\n".join(lines)
    if not records:
        records = _text_records(text, warnings)
    return records, text


def _text_records(text: str, warnings: list[str]) -> list[dict]:
    records = []
    # Plain text candidates are never presented as a faithfully reconstructed
    # PDF table: columns may have been interleaved by the source extractor.
    warnings.append("纯文本候选采用保守规则提取，可能漏项、错行或混入说明；请逐条对照原文件。空白等级与官网不会补猜。")
    for number, line in enumerate(text.splitlines(), 1):
        line = _clean(line)
        if not line or line.startswith(("#", "http://", "https://")) or len(line) > 320:
            continue
        line = re.sub(r"^\s*(?:[-*•]\s+|\d{1,4}[.、)）\s]+)", "", line)
        # A grade must be separated from the name, not inferred from its wording.
        grade = ""
        match = re.fullmatch(r"(.+?)\s+((?:[ABCＤDＥEＦF][类级]?|国家级|省级|校级|院级|一类|二类|三类|一级|二级|三级))", line, re.I)
        if match:
            line, grade = match.groups()
        if not re.search(r"竞赛|比赛|大赛|挑战赛|奥林匹克|建模|程序设计", line) or _header(line) in _HEADERS:
            continue
        if len(line) > 200 or re.search(r"请|如下|详见|通知|说明|认可.*清单|竞赛.*列表|竞赛.*目录", line):
            continue
        records.append({"name": line, "suggested_level": grade, "source_location": f"text:line-{number}"})
        if len(records) > MAX_RECORDS:
            raise ValueError(f"赛事记录超过 {MAX_RECORDS} 条")
    return records


def _markdown(text: str, warnings: list[str]):
    groups, rows = [], []
    for line in text.splitlines() + [""]:
        if "|" in line:
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
        elif rows:
            groups.append(rows)
            rows = []
    records = []
    for number, group in enumerate(groups, 1):
        records.extend(_table_records(group, f"markdown-table-{number}", warnings))
    return records or _text_records(text, warnings)


def _detect(payload: bytes, suffix: str) -> str:
    if payload.startswith(b"%PDF-"):
        return "pdf"
    if payload.startswith(b"PK"):
        with _archive(payload) as archive:
            names = set(archive.namelist())
        if "word/document.xml" in names:
            return "docx"
        if "xl/workbook.xml" in names:
            return "xlsx"
        raise ValueError("不支持的 Office 压缩文件类型")
    if suffix in {".docx", ".xlsx", ".pdf"}:
        raise ValueError("文件内容与文档扩展名不符或文件已损坏")
    text = _decode(payload).lstrip()
    if suffix == ".json" or text.startswith(("{", "[")):
        return "json"
    if suffix in {".csv", ".tsv"}:
        return "csv"
    if suffix in {".md", ".markdown"}:
        return "md"
    if suffix in {".txt", ""}:
        first = next((line for line in text.splitlines() if line.strip()), "")
        if any(separator in first for separator in (",", "\t")) and any(_header(cell) in _HEADERS for cell in re.split(r"[,\t]", first)):
            return "csv"
        return "txt"
    raise ValueError("支持 JSON、CSV、XLSX、DOCX、PDF、Markdown 和 TXT；请先转换旧版 DOC/XLS")


def import_catalog(source: Path | str, root: Path | str, *, overwrite: bool = False) -> dict:
    """Write ``config/catalog.json`` and a plain-text review aid, return draft.

    The caller must explicitly adopt the reviewed draft before scanning. This
    function never searches for official domains or inherits another college's
    recognition rules. Outputs are confined to the selected workspace.
    """
    source, root = Path(source), Path(root).resolve()
    if not source.is_file() or source.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError(f"导入文件不存在或超过 {MAX_SOURCE_BYTES // 1024 // 1024} MiB")
    payload = source.read_bytes()
    if len(payload) > MAX_SOURCE_BYTES:
        raise ValueError("导入文件体积超过上限")
    if not payload:
        raise ValueError("导入文件为空")
    format_name = _detect(payload, source.suffix.casefold())
    warnings = []
    if format_name == "json":
        text = _decode(payload)
        try:
            records = validate_catalog(json.loads(text))
        except (json.JSONDecodeError, RecursionError) as exc:
            raise ValueError("JSON 文件格式无效") from exc
    elif format_name == "xlsx":
        records, text = _xlsx(payload, warnings)
    elif format_name == "docx":
        records, text = _docx(payload, warnings)
    elif format_name == "pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError("读取 PDF 需要安装 pypdf；也可让 Agent 整理为 JSON 后导入") from exc
        try:
            reader = PdfReader(io.BytesIO(payload))
            if reader.is_encrypted:
                raise ValueError("请先移除 PDF 密码后导入")
            if len(reader.pages) > 200:
                raise ValueError("PDF 超过 200 页，请只导入竞赛名单部分")
            pages = []
            for page in reader.pages:
                pages.append((page.extract_text(extraction_mode="layout") or "") if page.get("/Contents") is not None else "")
                if sum(map(len, pages)) > MAX_EXTRACTED_CHARS:
                    raise ValueError("PDF 提取文字体积过大")
            text = "\n".join(pages)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("PDF 文字提取失败，请由 Agent 阅读后整理 JSON") from exc
        if not text.strip():
            warnings.append("PDF 未提取到可读文字，可能为扫描件；请让支持视觉的 Agent 或 OCR 工具阅读原文件，整理 JSON 后再导入。")
        records = _text_records(text, warnings)
    else:
        text = _decode(payload)
        if format_name == "csv":
            try:
                dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel_tab if source.suffix.casefold() == ".tsv" else csv.excel
            rows = []
            try:
                for row in csv.reader(io.StringIO(text), dialect, strict=True):
                    if len(row) > 200 or len(rows) >= MAX_RECORDS + 30:
                        raise ValueError("CSV 行列数超过导入上限，请只保留竞赛表格")
                    rows.append(row)
            except csv.Error as exc:
                raise ValueError("CSV 文件引号或字段格式损坏，请先整理表格") from exc
            records = _table_records(rows, "csv", warnings)
        elif format_name == "md":
            records = _markdown(text, warnings)
        else:
            records = _text_records(text, warnings)
    if len(text) > MAX_EXTRACTED_CHARS:
        raise ValueError("提取文字体积过大，请拆分后导入")
    if len(records) > MAX_RECORDS:
        raise ValueError(f"赛事记录超过 {MAX_RECORDS} 条")
    # Allocate missing IDs around explicit IDs; a later explicit row must not
    # collide with an ID assigned to an earlier unnumbered row.
    explicit_ids = [record["id"] for record in records if "id" in record]
    if len(explicit_ids) != len(set(explicit_ids)):
        raise ValueError("赛事 id 重复，请核对原文件或整理 JSON 后重新导入")
    taken = set(explicit_ids)
    next_id = 1
    for record in records:
        if "id" not in record:
            while next_id in taken:
                next_id += 1
            record["id"] = next_id
            taken.add(next_id)
        record["requires_confirmation"] = True
    records = validate_catalog({"records": records}) if records else []
    if any(record["suggested_level"] == "未分级" for record in records):
        warnings.append("部分赛事未提供明确等级，标为“未分级”；请根据学院原文件核对，程序未推断认可等级。")
    if any(record.get("duplicate_group") for record in records):
        warnings.append("发现同名赛事，已保留每条原记录并标记 duplicate_group；请核对不同等级、赛道或重复收录，未自动去重。")
    if not records:
        warnings.append("未得到可采用的赛事记录。已保留提取文字；请对照原件整理 records JSON 后重新导入。")
    document = {"schema_version": 1, "source": {"filename": source.name, "format": format_name, "sha256": hashlib.sha256(payload).hexdigest()}, "requires_confirmation": True, "review": {"status": "pending", "required": True, "warnings": list(dict.fromkeys(warnings))}, "records": records}
    config = root / "config"
    outputs = [config / "catalog.json", config / "catalog-import.txt"]
    if not all(output.resolve().is_relative_to(root) for output in outputs):
        raise ValueError("config 目录或输出文件通过符号链接指向工作目录之外")
    if not overwrite and any(output.exists() for output in outputs):
        raise FileExistsError("已有导入文件，请先核对现有清单；明确替换时使用 overwrite=True")
    if any(output.is_symlink() for output in outputs):
        raise ValueError("导入输出文件不能是符号链接")
    config.mkdir(parents=True, exist_ok=True)
    bodies = [json.dumps(document, ensure_ascii=False, indent=2) + "\n", text]
    for output, body in zip(outputs, bodies):
        # Exclusive temp creation also avoids following an attacker-supplied
        # catalog.json.tmp symlink left in a shared workspace.
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=config, prefix=".catalog-import-", delete=False) as handle:
            temporary = Path(handle.name)
            try:
                handle.write(body)
                handle.close()
                temporary.replace(output)
            finally:
                temporary.unlink(missing_ok=True)
    return document
