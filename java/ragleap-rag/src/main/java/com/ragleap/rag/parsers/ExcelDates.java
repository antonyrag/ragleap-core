package com.ragleap.rag.parsers;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.Locale;

/**
 * Excel serial numbers to the text Python prints for openpyxl's from_excel() result:
 * str(datetime), str(time) or str(timedelta). Returns null where openpyxl would hit an
 * OverflowError/ValueError (the caller then uses "#VALUE!").
 */
final class ExcelDates {

    private ExcelDates() {
    }

    static String fromExcel(double value, boolean date1904, boolean timedelta) {
        if (Double.isNaN(value) || Double.isInfinite(value)) {
            return null;
        }
        if (timedelta) {
            return timedeltaString(value);
        }
        double day = Math.floor(value);
        double fraction = value - day;
        long diffMs = (long) Math.rint(fraction * 86400.0 * 1000.0);
        if (value >= 0 && value < 1 && diffMs < 86_400_000L) {
            long sec = diffMs / 1000;
            long micro = (diffMs % 1000) * 1000;
            return String.format(Locale.ROOT, "%02d:%02d:%02d", sec / 3600, (sec % 3600) / 60, sec % 60)
                    + (micro != 0 ? String.format(Locale.ROOT, ".%06d", micro) : "");
        }
        if (value > 0 && value < 60 && !date1904) {
            day += 1;
        }
        if (Math.abs(day) > 4_000_000) {
            return null;
        }
        LocalDate epoch = date1904 ? LocalDate.of(1904, 1, 1) : LocalDate.of(1899, 12, 30);
        LocalDateTime dt = epoch.atStartOfDay().plusDays((long) day).plusNanos(diffMs * 1_000_000L);
        if (dt.getYear() < 1 || dt.getYear() > 9999) {
            return null;
        }
        int micro = dt.getNano() / 1000;
        return String.format(Locale.ROOT, "%04d-%02d-%02d %02d:%02d:%02d", dt.getYear(), dt.getMonthValue(),
                dt.getDayOfMonth(), dt.getHour(), dt.getMinute(), dt.getSecond())
                + (micro != 0 ? String.format(Locale.ROOT, ".%06d", micro) : "");
    }

    private static String timedeltaString(double value) {
        double micros = Math.rint(value * 86_400_000_000.0);
        if (Math.abs(micros) > 8.64e19) {
            return null;
        }
        long total = (long) micros;
        long sec = Math.floorDiv(total, 1_000_000L);
        long us = Math.floorMod(total, 1_000_000L);
        if (us != 0) {
            long q = us / 1000;
            long r = us % 1000;
            if (r > 500 || (r == 500 && (q & 1) == 1)) {
                q++;
            }
            total = sec * 1_000_000L + q * 1000;
            sec = Math.floorDiv(total, 1_000_000L);
            us = Math.floorMod(total, 1_000_000L);
        }
        long days = Math.floorDiv(sec, 86_400L);
        long rem = Math.floorMod(sec, 86_400L);
        String hms = String.format(Locale.ROOT, "%d:%02d:%02d", rem / 3600, (rem % 3600) / 60, rem % 60)
                + (us != 0 ? String.format(Locale.ROOT, ".%06d", us) : "");
        return days != 0 ? days + " day" + (Math.abs(days) == 1 ? "" : "s") + ", " + hms : hms;
    }
}
