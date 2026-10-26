/**
 * Markdown Dialect Contract (Client-Side)
 * Mirrors core/markdown_dialect.py regexes and transformation rules.
 */

export const RE_UNCERTAIN_FLAG = /\[\?(.+?)\?\]/g;
export const RE_DIAGRAM_TAG = /\{\{DIAGRAM:(d\d+)\}\}/g;
export const RE_MCQ_BLOCK = /<!--\s*mcq\s*-->([\s\S]*?)<!--\s*\/mcq\s*-->/gi;
export const RE_PAGEBREAK = /^\s*<!--\s*pagebreak\s*-->\s*$/gmi;
export const RE_UNDERLINE = /<u>([\s\S]*?)<\/u>/gi;
export const RE_MATH = /(\$\$(?:\\\$|[^\$])+?\$\$|\$(?:\\\$|[^\$\n])+?\$)/gs;

/**
 * Protects LaTeX math tokens by replacing them with unique placeholders.
 * Returns { protectedText, mathTokens }.
 */
export function protectMath(text) {
    const mathTokens = [];
    const protectedText = text.replace(RE_MATH, (match) => {
        const idx = mathTokens.length;
        mathTokens.push(match);
        return `__MATH_TOKEN_${idx}__`;
    });
    return { protectedText, mathTokens };
}

/**
 * Restores protected math tokens.
 */
export function restoreMath(text, mathTokens) {
    let result = text;
    for (let i = 0; i < mathTokens.length; i++) {
        result = result.replace(`__MATH_TOKEN_${i}__`, () => mathTokens[i]);
    }
    return result;
}

/**
 * Escapes question numbering so markdown parsers don't turn "01." or "(a)" into auto lists.
 * Must be called on text with math protected.
 */
export function applyNumberingEscape(text) {
    // "01. " -> "01\. "
    let res = text.replace(/^(\s*)(\d+)\.(\s)/gm, '$1$2\\.$3');
    // "(a) " -> "\(a) " or "(1) " -> "\(1) "
    res = res.replace(/^(\s*)\(([0-9]+|[a-zA-Z]|[ivxIVX]+)\)(\s)/gm, '$1\\($2)$3');
    return res;
}

/**
 * Counts uncertain flags [?...?] in text.
 */
export function countUncertainFlags(text) {
    if (!text) return 0;
    const matches = text.match(/\[\?(.+?)\?\]/g);
    return matches ? matches.length : 0;
}

/**
 * Strips uncertain flag wrappers: [?xyz?] -> xyz
 */
export function stripUncertainFlags(text) {
    if (!text) return '';
    return text.replace(/\[\?(.+?)\?\]/g, '$1');
}
