import React, { useEffect, useRef, useState } from "react";
import { X, ExternalLink, Search, Copy, Check } from "lucide-react";
import { fetchDocumentText, Citation } from "@/lib/api";
import { ScrollArea } from "@/components/ui/scroll-area";
import { motion, AnimatePresence } from "framer-motion";

interface SourceViewerProps {
    isOpen: boolean;
    onClose: () => void;
    documentId: string | null;
    documentName: string;
    citation: Citation | null;
}

export function SourceViewer({
    isOpen,
    onClose,
    documentId,
    documentName,
    citation
}: SourceViewerProps) {
    const [content, setContent] = useState<string>("");
    const [loading, setLoading] = useState(false);
    const [copied, setCopied] = useState(false);
    const scrollRef = useRef<HTMLDivElement>(null);
    const contentRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (isOpen && documentId) {
            const loadText = async () => {
                setLoading(true);
                try {
                    const data = await fetchDocumentText(documentId);
                    setContent(data.content);
                } catch (err) {
                    console.error("Failed to load document text:", err);
                    setContent("Failed to load document content.");
                } finally {
                    setLoading(false);
                }
            };
            loadText();
        }
    }, [isOpen, documentId]);

    useEffect(() => {
        if (!loading && content && citation && contentRef.current) {
            // Simple search for the citation context to scroll to it
            const elements = contentRef.current.getElementsByClassName("bg-primary/20");
            if (elements.length > 0) {
                elements[0].scrollIntoView({ behavior: "smooth", block: "center" });
            }
        }
    }, [loading, content, citation]);

    const highlightContent = (text: string, highlight: string | null) => {
        if (!highlight) return text;

        // Attempt to find the best match for the highlight text (which might be a chunk)
        const parts = text.split(highlight);
        if (parts.length === 1) return text; // No exact match

        return parts.map((part, i) => (
            <React.Fragment key={i}>
                {part}
                {i < parts.length - 1 && (
                    <mark className="bg-primary/20 text-foreground rounded-sm px-0.5 border-b-2 border-primary font-medium animate-pulse">
                        {highlight}
                    </mark>
                )}
            </React.Fragment>
        ));
    };

    const handleCopy = () => {
        navigator.clipboard.writeText(content);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    };

    if (!isOpen) return null;

    return (
        <motion.div
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 25, stiffness: 200 }}
            className="fixed inset-y-0 right-0 w-full sm:w-[500px] lg:w-[600px] bg-card border-l border-border shadow-2xl z-[100] flex flex-col"
        >
            <div className="flex items-center justify-between p-4 border-b border-border bg-muted/30">
                <div className="flex items-center gap-3">
                    <div className="p-2 rounded-lg bg-primary/10 text-primary">
                        <ExternalLink className="h-4 w-4" />
                    </div>
                    <div className="flex flex-col">
                        <h3 className="text-sm font-semibold truncate max-w-[200px] sm:max-w-xs">{documentName}</h3>
                        <span className="text-[10px] font-mono text-muted-foreground uppercase tracking-wider">Source Viewer</span>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={handleCopy}
                        className="p-2 rounded-md hover:bg-muted text-muted-foreground transition-colors"
                        title="Copy Text"
                    >
                        {copied ? <Check className="h-4 w-4 text-emerald-500" /> : <Copy className="h-4 w-4" />}
                    </button>
                    <button
                        onClick={onClose}
                        className="p-2 rounded-md hover:bg-muted text-muted-foreground transition-colors"
                    >
                        <X className="h-4 w-4" />
                    </button>
                </div>
            </div>

            <div className="flex-1 overflow-hidden relative">
                <ScrollArea className="h-full">
                    <div className="p-8 pb-20 font-serif leading-relaxed text-foreground/80 whitespace-pre-wrap selection:bg-primary/30" ref={contentRef}>
                        {loading ? (
                            <div className="flex flex-col items-center justify-center py-20 gap-4">
                                <div className="h-8 w-8 rounded-full border-2 border-primary border-t-transparent animate-spin" />
                                <p className="text-sm text-muted-foreground animate-pulse">Retrieving full source text...</p>
                            </div>
                        ) : (
                            highlightContent(content, citation?.context || null)
                        )}
                    </div>
                </ScrollArea>
            </div>

            <AnimatePresence>
                {citation && !loading && (
                    <motion.div
                        initial={{ y: 100 }}
                        animate={{ y: 0 }}
                        exit={{ y: 100 }}
                        className="absolute bottom-0 inset-x-0 p-4 bg-gradient-to-t from-background via-background to-transparent pt-10"
                    >
                        <div className="bg-primary/5 border border-primary/20 rounded-xl p-4 backdrop-blur-md shadow-lg border-l-4 border-l-primary">
                            <div className="flex items-center gap-2 mb-2">
                                <Search className="h-3.5 w-3.5 text-primary" />
                                <span className="text-[10px] font-bold uppercase tracking-widest text-primary">Inferred Context</span>
                            </div>
                            <p className="text-xs text-foreground/90 leading-relaxed line-clamp-3 italic">
                                "{citation.context}"
                            </p>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </motion.div>
    );
}
