import { useState, useEffect } from "react";
import { UserProfile, UserProfileUpdatePayload } from "@/lib/api";
import { X, Save, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

interface SettingsModalProps {
    isOpen: boolean;
    onClose: () => void;
    settings: UserProfile;
    onSave: (updates: UserProfileUpdatePayload) => Promise<void>;
}

const RISK_OPTIONS = [
    { value: "low", label: "Conservative", desc: "Capital preservation first" },
    { value: "medium", label: "Balanced", desc: "Growth with managed risk" },
    { value: "high", label: "Aggressive", desc: "Maximum growth potential" },
] as const;

const STYLE_OPTIONS = [
    { value: "simple", label: "Simple", desc: "Plain language, key points only" },
    { value: "deep", label: "Deep Dive", desc: "Full analysis with reasoning" },
] as const;

const EXPERIENCE_OPTIONS = [
    { value: "beginner", label: "Beginner", desc: "New to investing" },
    { value: "intermediate", label: "Intermediate", desc: "Some market experience" },
    { value: "expert", label: "Expert", desc: "Professional-level knowledge" },
] as const;

export function SettingsModal({ isOpen, onClose, settings, onSave }: SettingsModalProps) {
    const [riskTolerance, setRiskTolerance] = useState<"low" | "medium" | "high">(settings.risk_tolerance ?? "medium");
    const [preferredStyle, setPreferredStyle] = useState<"simple" | "deep">((settings.preferred_style as "simple" | "deep") ?? "deep");
    const [experienceLevel, setExperienceLevel] = useState<"beginner" | "intermediate" | "expert">((settings.experience_level as "beginner" | "intermediate" | "expert") ?? "intermediate");
    const [persona, setPersona] = useState(settings.custom_persona || "");
    const [isSaving, setIsSaving] = useState(false);

    useEffect(() => {
        setRiskTolerance(settings.risk_tolerance ?? "medium");
        setPreferredStyle((settings.preferred_style as "simple" | "deep") ?? "deep");
        setExperienceLevel((settings.experience_level as "beginner" | "intermediate" | "expert") ?? "intermediate");
        setPersona(settings.custom_persona || "");
    }, [settings]);

    if (!isOpen) return null;

    const handleSave = async () => {
        setIsSaving(true);
        try {
            await onSave({
                risk_tolerance: riskTolerance,
                preferred_style: preferredStyle,
                experience_level: experienceLevel,
                custom_persona: persona || null,
            });
            onClose();
        } catch (err) {
            console.error("Failed to save settings:", err);
        } finally {
            setIsSaving(false);
        }
    };

    return (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-background/80 backdrop-blur-sm animate-in fade-in duration-200">
            <div className="w-full max-w-lg bg-card border border-border rounded-xl shadow-2xl p-6 m-4 animate-in zoom-in-95 duration-200 max-h-[90vh] overflow-y-auto">
                <div className="flex items-center justify-between mb-6">
                    <div className="flex items-center gap-2 text-foreground font-semibold">
                        <div className="p-1.5 rounded-lg bg-primary/10 text-primary">
                            <Sparkles className="h-5 w-5" />
                        </div>
                        <span>Advisor Profile</span>
                    </div>
                    <button
                        onClick={onClose}
                        className="p-1 rounded-md hover:bg-muted text-muted-foreground hover:text-foreground transition-all"
                    >
                        <X className="h-5 w-5" />
                    </button>
                </div>

                <div className="space-y-6">
                    {/* Risk Tolerance */}
                    <div className="space-y-2">
                        <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                            Risk Tolerance
                        </label>
                        <div className="grid grid-cols-3 gap-2">
                            {RISK_OPTIONS.map(opt => (
                                <button
                                    key={opt.value}
                                    onClick={() => setRiskTolerance(opt.value)}
                                    className={cn(
                                        "flex flex-col items-start p-3 rounded-lg border text-left transition-all",
                                        riskTolerance === opt.value
                                            ? "border-primary bg-primary/5 text-primary"
                                            : "border-border hover:border-primary/50 text-muted-foreground"
                                    )}
                                >
                                    <span className="text-xs font-semibold">{opt.label}</span>
                                    <span className="text-[10px] mt-0.5 opacity-70">{opt.desc}</span>
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Response Style */}
                    <div className="space-y-2">
                        <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                            Response Style
                        </label>
                        <div className="grid grid-cols-2 gap-2">
                            {STYLE_OPTIONS.map(opt => (
                                <button
                                    key={opt.value}
                                    onClick={() => setPreferredStyle(opt.value)}
                                    className={cn(
                                        "flex flex-col items-start p-3 rounded-lg border text-left transition-all",
                                        preferredStyle === opt.value
                                            ? "border-primary bg-primary/5 text-primary"
                                            : "border-border hover:border-primary/50 text-muted-foreground"
                                    )}
                                >
                                    <span className="text-xs font-semibold">{opt.label}</span>
                                    <span className="text-[10px] mt-0.5 opacity-70">{opt.desc}</span>
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Experience Level */}
                    <div className="space-y-2">
                        <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                            Experience Level
                        </label>
                        <div className="grid grid-cols-3 gap-2">
                            {EXPERIENCE_OPTIONS.map(opt => (
                                <button
                                    key={opt.value}
                                    onClick={() => setExperienceLevel(opt.value)}
                                    className={cn(
                                        "flex flex-col items-start p-3 rounded-lg border text-left transition-all",
                                        experienceLevel === opt.value
                                            ? "border-primary bg-primary/5 text-primary"
                                            : "border-border hover:border-primary/50 text-muted-foreground"
                                    )}
                                >
                                    <span className="text-xs font-semibold">{opt.label}</span>
                                    <span className="text-[10px] mt-0.5 opacity-70">{opt.desc}</span>
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Custom Persona */}
                    <div className="space-y-2">
                        <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                            Behavioral Preferences <span className="normal-case tracking-normal opacity-50">(optional)</span>
                        </label>
                        <textarea
                            value={persona}
                            onChange={(e) => setPersona(e.target.value)}
                            maxLength={500}
                            placeholder='e.g. "Focus on long-term ETFs", "Always explain macro context first", "Prioritize downside risk".'
                            className="w-full h-28 bg-background border border-border rounded-lg p-4 text-sm focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none transition-all resize-none placeholder:text-muted-foreground/30"
                        />
                        <p className="text-[10px] text-muted-foreground/50 text-right">{persona.length}/500</p>
                    </div>
                </div>

                <div className="mt-6 flex justify-end gap-3 pt-4 border-t border-border">
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
                            <><Save className="h-4 w-4" /> Save Profile</>
                        )}
                    </button>
                </div>
            </div>
        </div>
    );
}
