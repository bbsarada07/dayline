/**
 * Code 128 (code set B) encoder for ID card barcodes. Code set B covers printable
 * ASCII (space to "~"), which is everything a roll number uses.
 *
 * Each symbol is six alternating bar/space widths (the stop symbol has seven).
 * Checked against the JsBarcode reference encoder; see the Phase 4 report.
 */

const PATTERNS = [
  "212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312", "132212", "221213",
  "221312", "231212", "112232", "122132", "122231", "113222", "123122", "123221", "223211", "221132",
  "221231", "213212", "223112", "312131", "311222", "321122", "321221", "312212", "322112", "322211",
  "212123", "212321", "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313",
  "231113", "231311", "112133", "112331", "132131", "113123", "113321", "133121", "313121", "211331",
  "231131", "213113", "213311", "213131", "311123", "311321", "331121", "312113", "312311", "332111",
  "314111", "221411", "431111", "111224", "111422", "121124", "121421", "141122", "141221", "112214",
  "112412", "122114", "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111",
  "111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112", "421211", "212141",
  "214121", "412121", "111143", "111341", "131141", "114113", "114311", "411113", "411311", "113141",
  "114131", "311141", "411131", "211412", "211214", "211232", "2331112",
];

const START_B = 104;
const STOP = 106;

/** True if `text` can be encoded in code set B. */
export function canEncode(text: string): boolean {
  return text.length > 0 && [...text].every((c) => c.charCodeAt(0) >= 32 && c.charCodeAt(0) <= 126);
}

/** Bars as a string of "1" (bar) and "0" (space) modules, quiet zones not included. */
export function encodeCode128B(text: string): string {
  if (!canEncode(text)) throw new Error("Code 128 B only encodes printable ASCII");
  const values = [...text].map((c) => c.charCodeAt(0) - 32);
  const checksum = values.reduce((sum, value, index) => sum + value * (index + 1), START_B) % 103;
  return [START_B, ...values, checksum, STOP]
    .map((symbol) =>
      [...PATTERNS[symbol]]
        .map((width, i) => (i % 2 === 0 ? "1" : "0").repeat(Number(width)))
        .join(""),
    )
    .join("");
}
