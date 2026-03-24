import { useState, useEffect } from "react";
import { UserSettings } from "@/lib/api";
import { Settings, X, Save, Sparkles } from "lucide-react";

interface SettingsModalProps {
    isOpen: boolean;
    onClose: () => void;
    settings: UserSettings;
    onSave: (persona: string) => Promise<void>;
}

export function SettingsModal({ isOpen, onClose, settings, onSave }: SettingsModalProps) {
    const [persona, setPersona] = useState(settings.custom_persona || "");
    const [isSaving, setIsSaving] = useState(false);

    // Sync state when settings prop changes (e.g. after initial fetch)
    useEffect(() => {
        setPersona(settings.custom_persona || "");
    }, [settings.custom_persona]);

    if (!isOpen) return null;

    const handleSave = async () => {
        setIsSaving(true);
        try {
            await onSave(persona);
            onClose();
        } catch (err) {
            console.error("Failed to save settings:", err);
        } finally {
            setIsSaving(false);
        }
    };

    return (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-background/80 backdrop-blur-sm animate-in fade-in duration-200">
            <div className="w-full max-w-lg bg-card border border-border rounded-xl shadow-2xl p-6 m-4 animate-in zoom-in-95 duration-200">
                <div className="flex items-center justify-between mb-6">
                    <div className="flex items-center gap-2 text-foreground font-semibold">
                        <div className="p-1.5 rounded-lg bg-primary/10 text-primary">
                            <Sparkles className="h-5 w-5" />
                        </div>
                        <span>AI Persona Customization</span>
                    </div>
                    <button
                        onClick={onClose}
                        className="p-1 rounded-md hover:bg-muted text-muted-foreground hover:text-foreground transition-all"
                    >
                        <X className="h-5 w-5" />
                    </button>
                </div>

                <div className="space-y-4">
                    <div className="p-3 rounded-lg bg-primary/5 border border-primary/10">
                        <p className="text-sm text-primary/80 leading-relaxed font-normal">
                            Instruct your AI advisor on how to behave. This will be applied to every response, alongside the core financial safety rules.
                        </p>
                    </div>

                    <div className="space-y-2">
                        <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                            Behavioral Preferences
                        </label>
                        <textarea
                            value={persona}
                            onChange={(e) => setPersona(e.target.value)}
                            placeholder='e.g. "Focus on long-term ETFs", "Use very simple language", "Be more aggressive with risk analysis", "Always explain the Hebrew macro context first".'
                            className="w-full h-44 bg-background border border-border rounded-lg p-4 text-sm focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none transition-all resize-none placeholder:text-muted-foreground/30"
                        />
                    </div>

                    <div className="flex items-center gap-2 text-[11px] text-muted-foreground/60 italic">
                        <span>* These preferences are stored securely and applied to your specific session.</span>
                    </div>
                </div>

                <div className="mt-8 flex justify-end gap-3 pt-4 border-t border-border">
                    <button
                        onClick={onClose}
                        className="px-4 py-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
                    >
                        Cancel
                    </button>
                    <button
                        onClick={handleSave}
                        disabled={isSaving}
                        className="flex items-center gap-2 px-6 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:opacity-90 active:scale-95 transition-all disabled:opacity-50 disabled:pointer-events-none shadow-lg shadow-primary/20"
                    >
                        {isSaving ? (
                            <span className="flex items-center gap-2">
                                <div className="h-3 w-3 border-2 border-primary-foreground/30 border-t-primary-foreground rounded-full animate-spin" />
                                Saving...
                            </span>
                        ) : (
                            <><Save className="h-4 w-4" /> Save Persona</>
                        )}
                    </button>
                </div>
            </div>
        </div>
    );
}
