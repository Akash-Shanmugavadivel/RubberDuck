import { Check, Copy } from "lucide-react";
import { isValidElement, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

function CodeBlock({ children }: { children: ReactNode }) {
  const [copied, setCopied] = useState(false);
  const element = isValidElement<{ children?: ReactNode; className?: string }>(children) ? children : null;
  const code = String(element?.props.children ?? "").replace(/\n$/, "");
  const language = element?.props.className?.replace("language-", "") ?? "code";

  async function copy() {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return <div className="markdown-code"><div><span>{language}</span><button type="button" onClick={() => void copy()}>{copied ? <Check/> : <Copy/>}{copied ? "Copied" : "Copy"}</button></div><pre><code className={element?.props.className}>{code}</code></pre></div>;
}

export function MarkdownMessage({ children }: { children: string }) {
  return <div className="markdown-body"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{
    pre: ({ children: code }) => <CodeBlock>{code}</CodeBlock>,
    a: ({ children: label, ...props }) => <a {...props} target="_blank" rel="noreferrer">{label}</a>,
  }}>{children}</ReactMarkdown></div>;
}
