import DOMPurify from 'dompurify';
import { marked } from 'marked';

const renderer = new marked.Renderer();
renderer.table = (header: string, body: string) => {
  return `<div class="table-wrapper"><table>${header}${body}</table></div>`;
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
