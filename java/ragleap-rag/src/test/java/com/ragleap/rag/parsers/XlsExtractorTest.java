package com.ragleap.rag.parsers;

import org.apache.poi.hssf.usermodel.HSSFWorkbook;
import org.apache.poi.ss.usermodel.Cell;
import org.apache.poi.ss.usermodel.FormulaError;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.junit.jupiter.api.Test;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Builds real .xls files with POI. Exact xlrd behaviour is covered by PythonParityFixturesTest. */
class XlsExtractorTest {

    private interface Builder {
        void build(HSSFWorkbook wb);
    }

    private static byte[] xls(Builder b) throws IOException {
        try (HSSFWorkbook wb = new HSSFWorkbook(); ByteArrayOutputStream bos = new ByteArrayOutputStream()) {
            b.build(wb);
            wb.write(bos);
            return bos.toByteArray();
        }
    }

    private static String parse(byte[] raw) {
        return DocumentParser.extractText("a.xls", raw);
    }

    @Test void marker() throws IOException {
        byte[] raw = xls(wb -> wb.createSheet("s1").createRow(0).createCell(0).setCellValue("ragleapmarker"));
        assertEquals("[Sheet: s1]\nragleapmarker", parse(raw));
        assertEquals("[Sheet: s1]\nragleapmarker", DocumentParser.extractText("A.XLS", raw));
    }

    @Test void numbersPrintAsPythonFloatsAndBooleansAsOneOrZero() throws IOException {
        byte[] raw = xls(wb -> {
            Row r = wb.createSheet("n").createRow(0);
            r.createCell(0).setCellValue(1);
            r.createCell(1).setCellValue(1.5);
            r.createCell(2).setCellValue(1e25);
            r.createCell(3).setCellValue(true);
            r.createCell(4).setCellValue(false);
            r.createCell(5).setCellValue(0.1 + 0.2);
        });
        assertEquals("[Sheet: n]\n1.0\t1.5\t1e+25\t1\t0\t0.30000000000000004", parse(raw));
    }

    @Test void emptyCellsAreSkippedWithoutLeavingTabs() throws IOException {
        byte[] raw = xls(wb -> {
            Row r = wb.createSheet("g").createRow(0);
            r.createCell(0).setCellValue("a");
            r.createCell(2).setCellValue("b");
        });
        assertEquals("[Sheet: g]\na\tb", parse(raw));
    }

    @Test void emptyStringAndWhitespaceOnlyRowsAreDropped() throws IOException {
        byte[] raw = xls(wb -> {
            Sheet s = wb.createSheet("w");
            s.createRow(0).createCell(0).setCellValue("");
            s.createRow(1).createCell(0).setCellValue("   ");
            s.createRow(3).createCell(0).setCellValue("kept");
        });
        assertEquals("[Sheet: w]\nkept", parse(raw));
    }

    @Test void everySheetGetsAHeaderEvenWhenEmpty() throws IOException {
        byte[] raw = xls(wb -> {
            wb.createSheet("one").createRow(0).createCell(0).setCellValue("x");
            wb.createSheet("two");
        });
        assertEquals("[Sheet: one]\nx\n[Sheet: two]", parse(raw));
    }

    @Test void errorCellsPrintTheirNumericCode() throws IOException {
        byte[] raw = xls(wb -> {
            Cell c = wb.createSheet("e").createRow(0).createCell(0);
            c.setCellErrorValue(FormulaError.DIV0.getCode());
        });
        assertEquals("[Sheet: e]\n7", parse(raw));
    }

    @Test void formulaCellsPrintTheirCachedValue() throws IOException {
        byte[] raw = xls(wb -> {
            Cell c = wb.createSheet("f").createRow(0).createCell(0);
            c.setCellFormula("1+1");
            wb.getCreationHelper().createFormulaEvaluator().evaluateFormulaCell(c);
        });
        assertEquals("[Sheet: f]\n2.0", parse(raw));
    }

    @Test void garbageIsRejected() {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                () -> parse("this is not a workbook".getBytes(StandardCharsets.UTF_8)));
        assertTrue(ex.getMessage().startsWith("Could not read XLS"));
    }
}
