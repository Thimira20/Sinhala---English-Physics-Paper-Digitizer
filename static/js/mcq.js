/**
 * MCQ Layout Switcher & Canonical Formatter.
 * Handles parsing, layout conversion (row5, grid32, grid2, list, as_original),
 * and layout constraint checks.
 */

export const MCQ_LAYOUTS = [
    { id: 'as_original', label: 'As original' },
    { id: 'row5', label: '1×5 row' },
    { id: 'grid32', label: '3-column grid' },
    { id: 'grid2', label: '2-column grid' },
    { id: 'list', label: 'Vertical list' }
];

/**
 * Parses options from an MCQ block inner text.
 * Returns array of { label: string, content: string }
 */
export function parseOptions(blockContent) {
    if (!blockContent) return [];

    let cleaned = blockContent.trim();

    // Check if it's a pipe table
    if (cleaned.includes('|')) {
        const lines = cleaned.split('\n').map(l => l.trim()).filter(Boolean);
        const cellContents = [];
        for (const line of lines) {
            // Skip markdown table divider line: |---|---|
            if (/^\|[\s\-:|]+\|$/.test(line)) continue;
            // Split line by '|'
            const parts = line.split('|').map(p => p.trim());
            // Drop leading/trailing empty parts from outer pipes
            if (line.startsWith('|') && parts.length > 0) parts.shift();
            if (line.endsWith('|') && parts.length > 0) parts.pop();

            for (const part of parts) {
                if (part) cellContents.push(part);
            }
        }

        // Parse labels from cell contents
        const options = [];
        for (const cell of cellContents) {
            // Find label like (1), (2), (a), (i), A.
            const match = cell.match(/^(\([0-9a-zA-ZivxIVX]+\)|[0-9a-zA-Z]\.)\s*(.*)$/s);
            if (match) {
                options.push({
                    label: match[1],
                    content: match[2].trim()
                });
            } else if (options.length > 0) {
                // Continuation
                options[options.length - 1].content += ' ' + cell;
            }
        }
        if (options.length > 0) return options;
    }

    // Otherwise, parse as line/paragraph-based list
    const labelRegex = /(?:^|\n\s*)(\([0-9a-zA-ZivxIVX]+\)|[0-9a-zA-Z]\.)\s*/g;
    const matches = [...cleaned.matchAll(labelRegex)];
    if (matches.length === 0) return [];

    const options = [];
    for (let i = 0; i < matches.length; i++) {
        const cur = matches[i];
        const next = matches[i + 1];
        const label = cur[1];
        const startIdx = cur.index + cur[0].length;
        const endIdx = next ? next.index : cleaned.length;
        const content = cleaned.substring(startIdx, endIdx).trim();
        options.push({ label, content });
    }

    return options;
}

/**
 * Detects current layout of an MCQ block text.
 */
export function detectLayout(blockContent) {
    const trimmed = blockContent.trim();
    if (!trimmed.includes('|')) return 'list';

    const lines = trimmed.split('\n').filter(l => l.trim() && !/^\|[\s\-:|]+\|$/.test(l.trim()));
    // Check columns in first data row
    const firstRow = lines.find(l => l.includes('|'));
    if (!firstRow) return 'list';

    const cols = firstRow.split('|').filter(c => c.trim().length > 0).length;
    if (cols >= 5) return 'row5';
    if (cols === 3) return 'grid32';
    if (cols === 2) return 'grid2';
    return 'list';
}

/**
 * Checks if options allow table/grid layouts or must strictly use vertical list.
 * Rule: Options containing '$$' or > 120 characters can only use 'list'.
 */
export function canUseGridLayout(options) {
    for (const opt of options) {
        if (opt.content.includes('$$')) return false;
        if (opt.content.length > 120) return false;
    }
    return true;
}

/**
 * Emits canonical MCQ block Markdown according to the specified layout.
 */
export function emit(options, layout) {
    if (!options || options.length === 0) return '';

    if (layout === 'list' || (!canUseGridLayout(options) && layout !== 'as_original')) {
        const body = options.map(o => `${o.label} ${o.content}`).join('\n\n');
        return `<!-- mcq -->\n${body}\n<!-- /mcq -->`;
    }

    let colCount = 5;
    if (layout === 'row5') colCount = 5;
    else if (layout === 'grid32') colCount = 3;
    else if (layout === 'grid2') colCount = 2;

    const header = '| ' + Array(colCount).fill(' ').join(' | ') + ' |';
    const divider = '|' + Array(colCount).fill('---').join('|') + '|';

    const rows = [];
    for (let i = 0; i < options.length; i += colCount) {
        const slice = options.slice(i, i + colCount);
        const cells = slice.map(o => `${o.label} ${o.content}`);
        while (cells.length < colCount) {
            cells.push(' ');
        }
        rows.push('| ' + cells.join(' | ') + ' |');
    }

    const table = [header, divider, ...rows].join('\n');
    return `<!-- mcq -->\n${table}\n<!-- /mcq -->`;
}
