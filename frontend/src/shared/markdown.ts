import DOMPurify from 'dompurify';
import { marked } from 'marked';

const renderer = new marked.Renderer();
// eslint-disable-next-line @typescript-eslint/no-explicit-any
renderer.table = (token: any) => {
  const headerHtml = token.header.map((c: any) => renderer.tablecell(c)).join('');
  const headerRow = renderer.tablerow({ text: headerHtml });
  const bodyHtml = token.rows.map((row: any[]) => {
    const cells = row.map((c: any) => renderer.tablecell(c)).join('');
    return renderer.tablerow({ text: cells });
  }).join('');
  return `<div class="table-wrapper"><table>${headerRow}${bodyHtml}</table></div>`;
};

marked.setOptions({ breaks: true, gfm: true, renderer });

let hookInstalled = false;

function ensureHookInstalled() {
  if (hookInstalled) {
    return;
  }
  DOMPurify.addHook('afterSanitizeAttributes', (node) => {
    if (node.tagName === 'A') {
      node.setAttribute('target', '_blank');
      node.setAttribute('rel', 'noopener');
    }
  });
  hookInstalled = true;
}

export function renderMarkdown(text: string): string {
  if (!text) {
    return '';
  }
  ensureHookInstalled();
  return DOMPurify.sanitize(marked.parse(text) as string);
}
