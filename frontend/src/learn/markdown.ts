import { Marked, Renderer } from "marked";

// Lessons are our own files, bundled at build time. Outside links open in a new tab.
const markdown = new Marked({
  gfm: true,
  renderer: {
    link(token) {
      const html = Renderer.prototype.link.call(this, token);
      return /^https?:/.test(token.href) ? html.replace("<a ", '<a target="_blank" rel="noopener noreferrer" ') : html;
    },
  },
});

export function renderMarkdown(text: string): string {
  return markdown.parse(text, { async: false });
}
