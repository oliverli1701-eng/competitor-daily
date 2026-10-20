import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from xml.sax.saxutils import escape

from contest_daily.catalog_io import import_catalog, validate_catalog


def office_archive(members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def spreadsheet(rows, *, external=False):
    sheet_rows = []
    for row_index, row in enumerate(rows, 1):
        cells = [f'<c r="{chr(65+column)}{row_index}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>' for column, value in enumerate(row)]
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return office_archive({
        "xl/workbook.xml": '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="学院原表" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"' + (' TargetMode="External"' if external else '') + '/></Relationships>',
        "xl/worksheets/sheet1.xml": '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + ''.join(sheet_rows) + '</sheetData></worksheet>',
    })


def word_document(rows):
    body = '<w:p><w:r><w:t>示例学院竞赛认可清单</w:t></w:r></w:p><w:tbl>'
    for row in rows:
        body += '<w:tr>' + ''.join(f'<w:tc><w:p><w:r><w:t>{escape(str(cell))}</w:t></w:r></w:p></w:tc>' for cell in row) + '</w:tr>'
    body += '</w:tbl>'
    return office_archive({"word/document.xml": '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + body + '</w:body></w:document>'})


class CatalogImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.workspace = self.base / "workspace"

    def import_bytes(self, filename, payload, **kwargs):
        source = self.base / filename
        source.write_bytes(payload)
        return import_catalog(source, self.workspace, **kwargs)

    def import_text(self, filename, text, **kwargs):
        return self.import_bytes(filename, text.encode("utf-8"), **kwargs)

    def test_agent_prepared_json_still_requires_review_and_cannot_configure_runtime(self):
        document = self.import_text("catalog.json", json.dumps({"review": {"status": "confirmed"}, "records": [{"id": 9, "name": "全国大学生数学建模竞赛", "suggested_level": "甲类", "requires_confirmation": False, "official_urls": ["https://example.edu/contest"], "shell_command": "do-not-run"}], "api_key": "do-not-copy"}, ensure_ascii=False))
        self.assertEqual(document["review"]["status"], "pending")
        self.assertTrue(document["requires_confirmation"])
        self.assertTrue(document["records"][0]["requires_confirmation"])
        self.assertEqual(document["records"][0]["suggested_level"], "甲类")
        self.assertNotIn("api_key", document)
        self.assertNotIn("shell_command", document["records"][0])
        persisted = json.loads((self.workspace / "config/catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(document, persisted)
        self.assertEqual(document["source"]["filename"], "catalog.json")
        self.assertEqual(len(document["source"]["sha256"]), 64)

    def test_json_duplicate_ids_rejected_before_any_files_written(self):
        with self.assertRaisesRegex(ValueError, "唯一"):
            self.import_text("duplicate.json", '[{"id":1,"name":"数学建模竞赛"},{"id":1,"name":"程序设计竞赛"}]')
        self.assertFalse(self.workspace.exists())

    def test_duplicate_names_preserve_original_rows_and_conflicting_levels(self):
        document = self.import_text("same.csv", "序号,赛事名称,认可等级\n35,全国大学生物联网设计竞赛,A\n40,全国大学生物联网设计竞赛,B\n")
        self.assertEqual([record["suggested_level"] for record in document["records"]], ["A", "B"])
        self.assertEqual([record["id"] for record in document["records"]], [35, 40])
        self.assertEqual(document["records"][0]["duplicate_group"], [35, 40])
        self.assertTrue(any("同名" in warning for warning in document["review"]["warnings"]))

    def test_csv_supports_utf8_bom_quotes_and_original_college_labels(self):
        document = self.import_bytes("college.csv", '\ufeff序号,竞赛名称,竞赛等级,官网\n7,"数学建模,程序设计竞赛",学院重点推荐,https://example.edu/rules\n'.encode("utf-8"))
        self.assertEqual(document["records"][0]["name"], "数学建模,程序设计竞赛")
        self.assertEqual(document["records"][0]["suggested_level"], "学院重点推荐")
        self.assertEqual(document["records"][0]["official_urls"], ["https://example.edu/rules"])

    def test_incomplete_table_keeps_ungraded_event_and_reports_missing_name(self):
        document = self.import_text("incomplete.csv", "id,name,level\n1,数学建模竞赛\n2,,A\n")
        self.assertEqual(len(document["records"]), 1)
        self.assertEqual(document["records"][0]["suggested_level"], "未分级")
        self.assertTrue(any("缺少赛事名称" in warning for warning in document["review"]["warnings"]))
        self.assertTrue(any("未分级" in warning for warning in document["review"]["warnings"]))

    def test_missing_ids_do_not_collide_with_later_explicit_id(self):
        document = self.import_text("ids.csv", "id,name\n,数学建模竞赛\n1,程序设计竞赛\n")
        self.assertEqual([record["id"] for record in document["records"]], [2, 1])

    def test_unrecognized_table_retains_source_instead_of_inventing_fields(self):
        document = self.import_text("unknown.csv", "列甲,列乙\n数学建模竞赛,A\n")
        self.assertEqual(document["records"], [])
        self.assertIn("数学建模竞赛", (self.workspace / "config/catalog-import.txt").read_text(encoding="utf-8"))
        self.assertTrue(any("未识别" in warning for warning in document["review"]["warnings"]))

    def test_malformed_csv_quote_is_not_silently_adopted(self):
        with self.assertRaisesRegex(ValueError, "CSV"):
            self.import_text("broken.csv", 'name,level\n"数学建模竞赛,A\n')
        self.assertFalse(self.workspace.exists())

    def test_csv_and_text_record_bounds_prevent_unbounded_candidate_lists(self):
        with patch("contest_daily.catalog_io.MAX_RECORDS", 1):
            with self.assertRaisesRegex(ValueError, "超过"):
                self.import_text("many.csv", "name\n数学建模竞赛\n程序设计竞赛\n")
            with self.assertRaisesRegex(ValueError, "超过"):
                self.import_text("many.txt", "数学建模竞赛\n程序设计竞赛\n")

    def test_true_xlsx_zip_xml_is_read_without_excel_or_third_party_library(self):
        document = self.import_bytes("list.xlsx", spreadsheet([["序号", "竞赛名称", "级别"], [8, "全国大学生电子设计竞赛", "B类"], [9, "挑战杯大学生课外学术科技作品竞赛", "A类"]]))
        self.assertEqual(document["source"]["format"], "xlsx")
        self.assertEqual([record["id"] for record in document["records"]], [8, 9])
        self.assertEqual(document["records"][1]["suggested_level"], "A类")

    def test_zip_magic_detects_docx_even_if_filename_is_unknown(self):
        document = self.import_bytes("uploaded.bin", word_document([["编号", "比赛名称", "认定等级"], [4, "大学生信息安全竞赛", "院级重点"]]))
        self.assertEqual(document["source"]["format"], "docx")
        self.assertEqual(document["records"][0]["name"], "大学生信息安全竞赛")
        self.assertEqual(document["records"][0]["suggested_level"], "院级重点")

    def test_xlsx_external_sheet_reference_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "外部"):
            self.import_bytes("external.xlsx", spreadsheet([["name"], ["数学建模竞赛"]], external=True))

    def test_malicious_docx_dtd_is_rejected_without_resolving_entities(self):
        payload = office_archive({"word/document.xml": '<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>'})
        with self.assertRaisesRegex(ValueError, "DTD"):
            self.import_bytes("unsafe.docx", payload)
        self.assertFalse(self.workspace.exists())

    def test_utf16_entity_declaration_also_rejected(self):
        xml = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE a [<!ENTITY x "secret">]><a>&x;</a>'.encode("utf-16")
        with self.assertRaisesRegex(ValueError, "DTD"):
            self.import_bytes("utf16.docx", office_archive({"word/document.xml": xml}))

    def test_traversal_member_in_office_archive_rejected(self):
        with self.assertRaisesRegex(ValueError, "路径"):
            self.import_bytes("unsafe.docx", office_archive({"../outside.txt": "do-not-write", "word/document.xml": "<root/>"}))
        self.assertFalse((self.base / "outside.txt").exists())

    def test_zip_uncompressed_size_bound_is_enforced(self):
        payload = word_document([["赛事名称"], ["数学建模竞赛"]])
        with patch("contest_daily.catalog_io.MAX_ZIP_BYTES", 10), self.assertRaisesRegex(ValueError, "体积"):
            self.import_bytes("large.docx", payload)

    def test_markdown_table_retains_rows_without_separator(self):
        document = self.import_text("catalog.md", "# 示例大学\n\n| 序号 | 竞赛名称 | 等级 |\n|---|---|---|\n| 12 | 计算机设计大赛 | A |\n| 13 | 数学建模竞赛 | |\n")
        self.assertEqual(len(document["records"]), 2)
        self.assertEqual(document["records"][1]["suggested_level"], "未分级")

    def test_plain_text_is_explicitly_uncertain_and_never_infers_national_level(self):
        document = self.import_text("catalog.txt", "学院认可竞赛列表\n1. 全国大学生数学建模竞赛\n2. 程序设计竞赛 A类\n请参赛学生详见通知\n")
        self.assertEqual(len(document["records"]), 2)
        self.assertEqual(document["records"][0]["suggested_level"], "未分级")
        self.assertNotIn("official_urls", document["records"][0])
        self.assertEqual(document["records"][1]["suggested_level"], "A类")
        self.assertTrue(any("可能漏项" in warning for warning in document["review"]["warnings"]))

    def test_pdf_real_text_extraction_and_pending_candidates(self):
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
        font = Path(__file__).resolve().parents[1] / "assets/ReportSans.ttc"
        if not font.exists():
            self.skipTest("可选中文字体未安装")
        pdfmetrics.registerFont(TTFont("CatalogImportTest", str(font), subfontIndex=0))
        buffer = io.BytesIO()
        document = canvas.Canvas(buffer)
        document.setFont("CatalogImportTest", 12)
        document.drawString(50, 800, "1. 全国大学生数学建模竞赛 A类")
        document.drawString(50, 775, "2. 大学生信息安全竞赛")
        document.save()
        imported = self.import_bytes("college.pdf", buffer.getvalue())
        self.assertEqual(imported["source"]["format"], "pdf")
        self.assertEqual(len(imported["records"]), 2)
        self.assertEqual(imported["records"][0]["suggested_level"], "A类")
        self.assertEqual(imported["review"]["status"], "pending")
        self.assertTrue(any("可能漏项" in warning for warning in imported["review"]["warnings"]))

    def test_blank_pdf_retains_pending_draft_with_ocr_guidance(self):
        from pypdf import PdfWriter
        buffer = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.write(buffer)
        document = self.import_bytes("scan.pdf", buffer.getvalue())
        self.assertEqual(document["records"], [])
        self.assertTrue(any("OCR" in warning for warning in document["review"]["warnings"]))

    def test_encrypted_pdf_rejected(self):
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.encrypt("not-a-real-password")
        buffer = io.BytesIO()
        writer.write(buffer)
        with self.assertRaisesRegex(ValueError, "密码"):
            self.import_bytes("private.pdf", buffer.getvalue())

    def test_unsafe_url_is_not_accepted_as_an_official_source(self):
        for url in ("file:///etc/passwd", "javascript:alert(1)", "https://user:password@example.edu", "https://example.edu/\nsecret"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_catalog({"records": [{"id": 1, "name": "示例竞赛", "official_urls": [url]}]})

    def test_misleading_extension_and_source_size_bound(self):
        with self.assertRaisesRegex(ValueError, "内容"):
            self.import_text("fake.pdf", "this is not a PDF")
        with patch("contest_daily.catalog_io.MAX_SOURCE_BYTES", 10), self.assertRaisesRegex(ValueError, "超过"):
            self.import_text("large.json", '[{"name":"过大文档竞赛"}]')

    def test_existing_catalog_requires_explicit_overwrite(self):
        first = self.import_text("first.json", '[{"id":1,"name":"第一竞赛"}]')
        with self.assertRaises(FileExistsError):
            self.import_text("second.json", '[{"id":2,"name":"第二竞赛"}]')
        self.assertEqual(json.loads((self.workspace / "config/catalog.json").read_text(encoding="utf-8"))["records"], first["records"])
        second = self.import_text("second.json", '[{"id":2,"name":"第二竞赛"}]', overwrite=True)
        self.assertEqual(second["records"][0]["id"], 2)
        self.assertEqual(list((self.workspace / "config").glob(".catalog-import-*")), [])

    def test_output_symlink_cannot_escape_workspace(self):
        outside = self.base / "outside"
        outside.mkdir()
        self.workspace.mkdir()
        try:
            (self.workspace / "config").symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("当前系统未授予创建符号链接权限")
        with self.assertRaisesRegex(ValueError, "符号链接"):
            self.import_text("list.json", '[{"id":1,"name":"数学建模竞赛"}]')
        self.assertEqual(list(outside.iterdir()), [])

    def test_invalid_empty_records_cannot_be_adopted(self):
        with self.assertRaisesRegex(ValueError, "records"):
            validate_catalog({"records": []})
        with self.assertRaisesRegex(ValueError, "唯一"):
            validate_catalog({"records": [{"id": True, "name": "数学建模竞赛"}]})


if __name__ == "__main__":
    unittest.main()
