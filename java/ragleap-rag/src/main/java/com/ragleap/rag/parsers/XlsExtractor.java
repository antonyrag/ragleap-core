package com.ragleap.rag.parsers;

import org.apache.poi.hssf.usermodel.HSSFWorkbook;
import org.apache.poi.ss.usermodel.Cell;
import org.apache.poi.ss.usermodel.CellType;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

/**
 * Legacy .xls text extraction. Java port of parsers.py's _extract_xls (xlrd), using Apache
 * POI (an optional dependency). Same output rules as xlrd: a "[Sheet: name]" line per sheet,
 * then each non-blank row's non-empty cells joined by tabs. Numbers are always floats printed
 * like Python (1.0, 1.5, 1e+25), dates are NOT converted (the raw serial number prints),
 * booleans print as 1/0, errors as their numeric code, formulas as their cached value.
 * Only BIFF8 (Excel 97 and later) files are readable; xlrd also reads older BIFF versions.
 */
final class XlsExtractor {

    private XlsExtractor() {
    }

    static String extract(byte[] raw) {
        List<String> parts = new ArrayList<>();
        try (HSSFWorkbook wb = new HSSFWorkbook(new ByteArrayInputStream(raw))) {
            for (int s = 0; s < wb.getNumberOfSheets(); s++) {
                Sheet sheet = wb.getSheetAt(s);
                parts.add("[Sheet: " + sheet.getSheetName() + "]");
                for (int r = sheet.getFirstRowNum(); r <= sheet.getLastRowNum(); r++) {
                    Row row = sheet.getRow(r);
                    if (row == null) {
                        continue;
                    }
                    List<String> cells = new ArrayList<>();
                    int last = row.getLastCellNum();
                    for (int c = 0; c < last; c++) {
                        String v = cellText(row.getCell(c));
                        if (v != null) {
                            cells.add(v);
                        }
                    }
                    String text = String.join("\t", cells);
                    if (!PyText.isBlank(text)) {
                        parts.add(text);
                    }
                }
            }
        } catch (IOException | RuntimeException e) {
            throw new IllegalArgumentException("Could not read XLS: " + e.getMessage(), e);
        }
        return String.join("\n", parts);
    }

    /** The text xlrd's str(value) would give, or null for a cell xlrd reports as empty. */
    private static String cellText(Cell cell) {
        if (cell == null) {
            return null;
        }
        CellType type = cell.getCellType();
        if (type == CellType.FORMULA) {
            type = cell.getCachedFormulaResultType();
        }
        return switch (type) {
            case NUMERIC -> PyFloat.repr(cell.getNumericCellValue());
            case STRING -> {
                String s = cell.getStringCellValue();
                yield s.isEmpty() ? null : s;
            }
            case BOOLEAN -> cell.getBooleanCellValue() ? "1" : "0";
            case ERROR -> Integer.toString(cell.getErrorCellValue() & 0xFF);
            default -> null;
        };
    }
}
