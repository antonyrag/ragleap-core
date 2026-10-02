package com.ragleap.rag.parsers;

import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.Charset;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.Arrays;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * RTF to plain text. Java port of the striprtf library's rtf_to_text, which
 * ragleap-rag's parsers.py uses for .rtf files. Same state machine and the same
 * quirks: a hex escape pending at the very end of the input is dropped, table
 * cells become "|", rows become newlines, and a hyperlink's URL (with its quotes)
 * is appended after the link text.
 *
 * <p>Errors that are exceptions in Python (undecodable bytes, a \\uc with no
 * number, a code point beyond U+10FFFF) throw IllegalArgumentException.
 */
final class RtfConverter {

    private RtfConverter() {
    }

    /** Control words that start a "destination" group whose content is not document text. */
    private static final String DESTINATIONS_TEXT = """
            aftncn aftnsep aftnsepc annotation atnauthor atndate atnicn atnid
            atnparent atnref atntime atrfend atrfstart author background
            bkmkend bkmkstart blipuid buptim category colorschememapping
            colortbl comment company creatim datafield datastore defchp defpap
            do doccomm docvar dptxbxtext ebcend ebcstart factoidname falt
            fchars ffdeftext ffentrymcr ffexitmcr ffformat ffhelptext ffl
            ffname ffstattext file filetbl fldinst fldtype
            fname fontemb fontfile fonttbl footer footerf footerl footerr
            footnote formfield ftncn ftnsep ftnsepc g generator gridtbl
            header headerf headerl headerr hl hlfr hlinkbase hlloc hlsrc
            hsv htmltag info keycode keywords latentstyles lchars levelnumbers
            leveltext lfolevel linkval list listlevel listname listoverride
            listoverridetable listpicture liststylename listtable listtext
            lsdlockedexcept macc maccPr mailmerge maln malnScr manager margPr
            mbar mbarPr mbaseJc mbegChr mborderBox mborderBoxPr mbox mboxPr
            mchr mcount mctrlPr md mdeg mdegHide mden mdiff mdPr me
            mendChr meqArr meqArrPr mf mfName mfPr mfunc mfuncPr mgroupChr
            mgroupChrPr mgrow mhideBot mhideLeft mhideRight mhideTop mhtmltag
            mlim mlimloc mlimlow mlimlowPr mlimupp mlimuppPr mm mmaddfieldname
            mmath mmathPict mmathPr mmaxdist mmc mmcJc mmconnectstr
            mmconnectstrdata mmcPr mmcs mmdatasource mmheadersource mmmailsubject
            mmodso mmodsofilter mmodsofldmpdata mmodsomappedname mmodsoname
            mmodsorecipdata mmodsosort mmodsosrc mmodsotable mmodsoudl
            mmodsoudldata mmodsouniquetag mmPr mmquery mmr mnary mnaryPr
            mnoBreak mnum mobjDist moMath moMathPara moMathParaPr mopEmu
            mphant mphantPr mplcHide mpos mr mrad mradPr mrPr msepChr
            mshow mshp msPre msPrePr msSub msSubPr msSubSup msSubSupPr msSup
            msSupPr mstrikeBLTR mstrikeH mstrikeTLBR mstrikeV msub msubHide
            msup msupHide mtransp mtype mvertJc mvfmf mvfml mvtof mvtol
            mzeroAsc mzeroDesc mzeroWid nesttableprops nextfile nonesttables
            objalias objclass objdata object objname objsect objtime oldcprops
            oldpprops oldsprops oldtprops oleclsid operator panose password
            passwordhash pgp pgptbl picprop pict pn pnseclvl pntext pntxta
            pntxtb printim private propname protend protstart protusertbl pxe
            result revtbl revtim rsidtbl rxe shp shpgrp shpinst
            shppict shprslt shptxt sn sp staticval stylesheet subject sv
            svb tc template themedata title txe ud upr userprops
            wgrffmtfilter windowcaption writereservation writereservhash xe xform
            xmlattrname xmlattrvalue xmlclose xmlname xmlnstbl
            xmlopen
            """;

    private static final Set<String> DESTINATIONS =
            new HashSet<>(Arrays.asList(DESTINATIONS_TEXT.trim().split("\\s+")));

    /** Translation of some special characters and control words. */
    private static final Map<String, String> SPECIAL = new HashMap<>();

    static {
        SPECIAL.put("par", "\n");
        SPECIAL.put("sect", "\n\n");
        SPECIAL.put("page", "\n\n");
        SPECIAL.put("line", "\n");
        SPECIAL.put("tab", "\t");
        SPECIAL.put("emdash", "\u2014");
        SPECIAL.put("endash", "\u2013");
        SPECIAL.put("emspace", "\u2003");
        SPECIAL.put("enspace", "\u2002");
        SPECIAL.put("qmspace", "\u2005");
        SPECIAL.put("bullet", "\u2022");
        SPECIAL.put("lquote", "\u2018");
        SPECIAL.put("rquote", "\u2019");
        SPECIAL.put("ldblquote", "\u201C");
        SPECIAL.put("rdblquote", "\u201D");
        SPECIAL.put("row", "\n");
        SPECIAL.put("cell", "|");
        SPECIAL.put("nestcell", "|");
        SPECIAL.put("~", "\u00A0");
        SPECIAL.put("\n", "\n");
        SPECIAL.put("\r", "\r");
        SPECIAL.put("{", "{");
        SPECIAL.put("}", "}");
        SPECIAL.put("\\", "\\");
        SPECIAL.put("-", "\u00AD");
        SPECIAL.put("_", "\u2011");
    }

    private static final int FLAGS =
            Pattern.CASE_INSENSITIVE | Pattern.UNICODE_CASE | Pattern.UNIX_LINES;

    /** Groups: 1 word, 2 numeric arg, 3 hex byte, 4 escaped char, 5 brace, 6 plain char. */
    private static final Pattern TOKEN = Pattern.compile(
            "\\\\([a-z]{1,32})(-?\\d{1,10})?[ ]?|\\\\'([0-9a-f]{2})|\\\\([^a-z])|([{}])|[\\r\\n]+|(.)",
            FLAGS);

    /** Captures links like link_text("http://dest") so the destination survives. */
    private static final Pattern HYPERLINKS = Pattern.compile(
            "(\\{\\\\field\\{\\s*\\\\\\*\\\\fldinst\\{.*HYPERLINK\\s(\".*\")\\}{2}\\s*\\{.*?\\s+(.*?)\\}{2,3})",
            FLAGS);

    private static final Charset DEFAULT_ENCODING = Charset.forName("windows-1252");

    static String rtfToText(String input) {
        String text = HYPERLINKS.matcher(input).replaceAll("$1($2)");

        Deque<long[]> stack = new ArrayDeque<>();
        boolean ignorable = false;
        long ucskip = 1;
        long curskip = 0;
        StringBuilder hexes = null;
        Charset encoding = DEFAULT_ENCODING;
        StringBuilder out = new StringBuilder();

        Matcher m = TOKEN.matcher(text);
        while (m.find()) {
            String word = m.group(1);
            String arg = m.group(2);
            String hex = m.group(3);
            String ch = m.group(4);
            String brace = m.group(5);
            String tchar = m.group(6);

            if (hexes != null && hex == null) {
                out.append(decodeHex(hexes.toString(), encoding));
                hexes = null;
            }
            if (brace != null) {
                curskip = 0;
                if (brace.equals("{")) {
                    stack.push(new long[] {ucskip, ignorable ? 1 : 0});
                } else if (!stack.isEmpty()) {
                    long[] state = stack.pop();
                    ucskip = state[0];
                    ignorable = state[1] == 1;
                } else {
                    // striprtf's own workaround for an unbalanced closing brace
                    ucskip = 0;
                    ignorable = true;
                }
            } else if (ch != null) {
                curskip = 0;
                String special = SPECIAL.get(ch);
                if (special != null) {
                    if (!ignorable) {
                        out.append(special);
                    }
                } else if (ch.equals("*")) {
                    ignorable = true;
                }
            } else if (word != null) {
                curskip = 0;
                if (DESTINATIONS.contains(word)) {
                    ignorable = true;
                } else if (word.equals("ansicpg")) {
                    encoding = charsetForCodepage(arg);
                }
                if (ignorable) {
                    // inside an ignorable group: nothing is emitted
                } else if (SPECIAL.containsKey(word)) {
                    out.append(SPECIAL.get(word));
                } else if (word.equals("uc")) {
                    if (arg == null) {
                        throw new IllegalArgumentException("Invalid RTF: \\uc has no numeric argument");
                    }
                    ucskip = Long.parseLong(arg);
                } else if (word.equals("u")) {
                    if (arg == null) {
                        curskip = ucskip;
                    } else {
                        long c = Long.parseLong(arg);
                        if (c < 0) {
                            c += 0x10000;
                        }
                        if (c > 0x10FFFF) {
                            throw new IllegalArgumentException(
                                    "Invalid RTF: unicode escape out of range: " + arg);
                        }
                        out.appendCodePoint((int) c);
                        curskip = ucskip;
                    }
                }
            } else if (hex != null) {
                if (curskip > 0) {
                    curskip--;
                } else if (!ignorable) {
                    if (hexes == null) {
                        hexes = new StringBuilder(hex);
                    } else {
                        hexes.append(hex);
                    }
                }
            } else if (tchar != null) {
                if (curskip > 0) {
                    curskip--;
                } else if (!ignorable) {
                    out.append(tchar);
                }
            }
        }
        // Like striprtf: a hex escape still pending here is dropped.
        return out.toString();
    }

    private static String decodeHex(String hex, Charset charset) {
        byte[] bytes = new byte[hex.length() / 2];
        for (int i = 0; i < bytes.length; i++) {
            bytes[i] = (byte) Integer.parseInt(hex.substring(2 * i, 2 * i + 2), 16);
        }
        try {
            return charset.newDecoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                    .decode(ByteBuffer.wrap(bytes))
                    .toString();
        } catch (CharacterCodingException e) {
            throw new IllegalArgumentException(
                    "Invalid RTF: could not decode escaped bytes as " + charset.name(), e);
        }
    }

    /** Python: encoding = f"cp{arg}", falling back to utf8 if the codec is unknown. */
    private static Charset charsetForCodepage(String arg) {
        if (arg == null || arg.equals("65001")) {
            return StandardCharsets.UTF_8;
        }
        String[] candidates = {"cp" + arg, "windows-" + arg, "x-windows-" + arg, "ms" + arg, "x-mswin-" + arg};
        for (String name : candidates) {
            try {
                return Charset.forName(name);
            } catch (IllegalArgumentException e) {
                // unknown charset name: try the next spelling
            }
        }
        return StandardCharsets.UTF_8;
    }
}
