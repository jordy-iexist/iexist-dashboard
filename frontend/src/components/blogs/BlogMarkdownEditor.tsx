"use client"

import { useEffect, useRef } from "react"
import { useEditor, EditorContent } from "@tiptap/react"
import StarterKit from "@tiptap/starter-kit"
import Link from "@tiptap/extension-link"
import { Markdown } from "tiptap-markdown"
import type { MarkdownStorage } from "tiptap-markdown"
import {
  Heading1,
  Heading2,
  Heading3,
  Bold,
  Italic,
  List,
  ListOrdered,
  Link2,
  Code,
  Quote,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type Props = {
  value: string
  onChange: (markdown: string) => void
  disabled?: boolean
}

function ToolbarButton({
  onClick,
  active,
  disabled,
  label,
  children,
}: {
  onClick: () => void
  active?: boolean
  disabled?: boolean
  label: string
  children: React.ReactNode
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className={cn(active && "bg-accent text-accent-foreground")}
    >
      {children}
    </Button>
  )
}

function getMarkdown(storage: unknown): string {
  return ((storage as Record<string, unknown>).markdown as MarkdownStorage).getMarkdown()
}

export function BlogMarkdownEditor({ value, onChange, disabled }: Props) {
  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange
  const valueRef = useRef(value)
  valueRef.current = value

  const editor = useEditor({
    extensions: [
      StarterKit.configure({ heading: { levels: [1, 2, 3] } }),
      Link.configure({ openOnClick: false }),
      Markdown,
    ],
    content: value,
    editable: !disabled,
    onUpdate({ editor }) {
      const md = getMarkdown(editor.storage)
      if (md !== valueRef.current) {
        onChangeRef.current(md)
      }
    },
  })

  useEffect(() => {
    if (!editor) return
    const current = getMarkdown(editor.storage)
    if (current !== value) {
      editor.commands.setContent(value)
    }
  }, [value, editor])

  useEffect(() => {
    if (!editor) return
    editor.setEditable(!disabled)
  }, [disabled, editor])

  const setLink = () => {
    if (!editor) return
    const previous = editor.getAttributes("link").href as string | undefined
    const url = window.prompt("URL", previous ?? "")
    if (url === null) return
    if (url === "") {
      editor.chain().focus().extendMarkRange("link").unsetLink().run()
      return
    }
    editor.chain().focus().extendMarkRange("link").setLink({ href: url }).run()
  }

  return (
    <div className={cn("rounded-md border bg-background", disabled && "opacity-50")}>
      <div className="flex flex-wrap gap-0.5 border-b px-2 py-1.5">
        <ToolbarButton
          label="Kop 1"
          onClick={() => editor?.chain().focus().toggleHeading({ level: 1 }).run()}
          active={editor?.isActive("heading", { level: 1 })}
          disabled={disabled}
        >
          <Heading1 />
        </ToolbarButton>
        <ToolbarButton
          label="Kop 2"
          onClick={() => editor?.chain().focus().toggleHeading({ level: 2 }).run()}
          active={editor?.isActive("heading", { level: 2 })}
          disabled={disabled}
        >
          <Heading2 />
        </ToolbarButton>
        <ToolbarButton
          label="Kop 3"
          onClick={() => editor?.chain().focus().toggleHeading({ level: 3 }).run()}
          active={editor?.isActive("heading", { level: 3 })}
          disabled={disabled}
        >
          <Heading3 />
        </ToolbarButton>
        <div className="mx-1 w-px self-stretch bg-border" />
        <ToolbarButton
          label="Vet"
          onClick={() => editor?.chain().focus().toggleBold().run()}
          active={editor?.isActive("bold")}
          disabled={disabled}
        >
          <Bold />
        </ToolbarButton>
        <ToolbarButton
          label="Cursief"
          onClick={() => editor?.chain().focus().toggleItalic().run()}
          active={editor?.isActive("italic")}
          disabled={disabled}
        >
          <Italic />
        </ToolbarButton>
        <div className="mx-1 w-px self-stretch bg-border" />
        <ToolbarButton
          label="Opsommingslijst"
          onClick={() => editor?.chain().focus().toggleBulletList().run()}
          active={editor?.isActive("bulletList")}
          disabled={disabled}
        >
          <List />
        </ToolbarButton>
        <ToolbarButton
          label="Genummerde lijst"
          onClick={() => editor?.chain().focus().toggleOrderedList().run()}
          active={editor?.isActive("orderedList")}
          disabled={disabled}
        >
          <ListOrdered />
        </ToolbarButton>
        <div className="mx-1 w-px self-stretch bg-border" />
        <ToolbarButton
          label="Link"
          onClick={setLink}
          active={editor?.isActive("link")}
          disabled={disabled}
        >
          <Link2 />
        </ToolbarButton>
        <ToolbarButton
          label="Inline code"
          onClick={() => editor?.chain().focus().toggleCode().run()}
          active={editor?.isActive("code")}
          disabled={disabled}
        >
          <Code />
        </ToolbarButton>
        <ToolbarButton
          label="Citaat"
          onClick={() => editor?.chain().focus().toggleBlockquote().run()}
          active={editor?.isActive("blockquote")}
          disabled={disabled}
        >
          <Quote />
        </ToolbarButton>
      </div>
      <EditorContent
        editor={editor}
        className="prose prose-sm max-w-none px-3 py-2 leading-7 [&_.tiptap]:min-h-96 [&_.tiptap]:outline-none"
      />
    </div>
  )
}
