import { useState, useRef, useEffect } from "react";
import { ArrowUp } from "lucide-react";

interface Props {
  onSend: (message: string) => void;
  isLoading: boolean;
}

export function ChatInput({ onSend, isLoading }: Props) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 160) + "px";
    }
  }, [value]);

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!trimmed || isLoading) return;
    onSend(trimmed);
    setValue("");
  };

  return (
    <div className="border-t border-border p-4">
      <div
        className={`surface-card flex items-end gap-2 p-2 transition-shadow duration-200 ${
          isLoading ? "input-glow-pulse" : ""
        }`}
      >
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleSubmit();
            }
          }}
          placeholder="Ask about your portfolio..."
          rows={1}
          className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground resize-none outline-none min-h-[36px] py-2 px-2"
        />
        <button
          onClick={handleSubmit}
          disabled={!value.trim() || isLoading}
          className="h-8 w-8 rounded flex items-center justify-center bg-primary text-primary-foreground disabled:opacity-30 transition-opacity duration-100 flex-shrink-0"
        >
          <ArrowUp className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
