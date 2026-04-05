import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Trash2, Plus, Upload, TrendingUp, RefreshCw, AlertCircle } from "lucide-react";
import { toast } from "sonner";
import {
    fetchPortfolioPositions,
    addPortfolioPosition,
    deletePortfolioPosition,
    importPortfolioFile,
    type PortfolioPosition,
} from "@/lib/api";

const TODAY = new Date().toISOString().split("T")[0];

export default function Portfolio() {
    const [positions, setPositions] = useState<PortfolioPosition[]>([]);
    const [loading, setLoading] = useState(true);
    const [showForm, setShowForm] = useState(false);
    const [importing, setImporting] = useState(false);
    const fileRef = useRef<HTMLInputElement>(null);

    // form state
    const [sym, setSym] = useState("");
    const [qty, setQty] = useState("");
    const [cost, setCost] = useState("");
    const [currency, setCurrency] = useState("USD");
    const [account, setAccount] = useState("default");
    const [posDate, setPosDate] = useState(TODAY);
    const [submitting, setSubmitting] = useState(false);

    const load = async () => {
        setLoading(true);
        try {
            setPositions(await fetchPortfolioPositions());
        } catch {
            toast.error("Failed to load portfolio");
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { load(); }, []);

    const handleAdd = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!sym.trim() || !qty) return;
        setSubmitting(true);
        try {
            await addPortfolioPosition({
                symbol: sym.trim().toUpperCase(),
                quantity: parseFloat(qty),
                cost_basis: cost ? parseFloat(cost) : null,
                currency: currency.toUpperCase().slice(0, 3),
                account: account || "default",
                date: posDate,
            });
            toast.success(`Added ${sym.toUpperCase()}`);
            setSym(""); setQty(""); setCost(""); setAccount("default"); setPosDate(TODAY);
            setShowForm(false);
            load();
        } catch {
            toast.error("Failed to add position");
        } finally {
            setSubmitting(false);
        }
    };

    const handleDelete = async (symbol: string, acct: string) => {
        try {
            await deletePortfolioPosition(symbol, acct);
            toast.success(`Removed ${symbol}`);
            setPositions(prev => prev.filter(p => !(p.symbol === symbol && p.account === acct)));
        } catch {
            toast.error("Failed to delete position");
        }
    };

    const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        setImporting(true);
        try {
            const res = await importPortfolioFile(file);
            if (res.rows_ingested > 0) {
                toast.success(`Imported ${res.rows_ingested} position(s)`);
                load();
            } else {
                toast.warning("No rows imported — check file format");
            }
            if (res.parse_errors.length > 0) {
                toast.warning(`${res.parse_errors.length} parse error(s) — check console`);
                console.warn("Import parse errors:", res.parse_errors);
            }
        } catch {
            toast.error("Import failed");
        } finally {
            setImporting(false);
            if (fileRef.current) fileRef.current.value = "";
        }
    };

    const totalCost = positions.reduce((s, p) => s + (p.cost_basis ?? 0) * p.quantity, 0);

    return (
        <div className="flex-1 overflow-auto bg-background p-6">
            {/* Header */}
            <div className="max-w-5xl mx-auto">
                <div className="flex items-center justify-between mb-6">
                    <div className="flex items-center gap-3">
                        <div className="p-2.5 rounded-xl bg-primary/10 text-primary">
                            <TrendingUp className="h-5 w-5" />
                        </div>
                        <div>
                            <h1 className="text-xl font-bold text-foreground">Portfolio</h1>
                            <p className="text-xs text-muted-foreground font-mono">
                                {positions.length} position{positions.length !== 1 ? "s" : ""} ·
                                Est. cost {totalCost > 0 ? `$${totalCost.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : "—"}
                            </p>
                        </div>
                    </div>

                    <div className="flex items-center gap-2">
                        <button
                            onClick={load}
                            className="p-2 rounded-lg hover:bg-muted transition-colors text-muted-foreground"
                            title="Refresh"
                        >
                            <RefreshCw className="h-4 w-4" />
                        </button>
                        <label className="cursor-pointer">
                            <input
                                ref={fileRef}
                                type="file"
                                accept=".csv,.pdf"
                                className="hidden"
                                onChange={handleImport}
                                disabled={importing}
                            />
                            <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border bg-muted/40 hover:bg-muted text-sm font-medium transition-colors text-foreground">
                                <Upload className={`h-3.5 w-3.5 ${importing ? "animate-spin" : ""}`} />
                                {importing ? "Importing…" : "Import CSV / PDF"}
                            </span>
                        </label>
                        <button
                            onClick={() => setShowForm(v => !v)}
                            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
                        >
                            <Plus className="h-3.5 w-3.5" />
                            Add Position
                        </button>
                    </div>
                </div>

                {/* Add Form */}
                <AnimatePresence>
                    {showForm && (
                        <motion.form
                            initial={{ opacity: 0, y: -8 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, y: -8 }}
                            onSubmit={handleAdd}
                            className="mb-5 p-4 rounded-xl border border-border/60 bg-card/60 backdrop-blur-sm grid grid-cols-2 sm:grid-cols-3 gap-3"
                        >
                            {[
                                { label: "Symbol *", value: sym, onChange: setSym, placeholder: "AAPL", required: true, className: "uppercase" },
                                { label: "Quantity *", value: qty, onChange: setQty, placeholder: "10", type: "number", required: true },
                                { label: "Avg Cost ($)", value: cost, onChange: setCost, placeholder: "150.00", type: "number" },
                                { label: "Currency", value: currency, onChange: setCurrency, placeholder: "USD" },
                                { label: "Account", value: account, onChange: setAccount, placeholder: "default" },
                                { label: "Date", value: posDate, onChange: setPosDate, type: "date" },
                            ].map(({ label, value, onChange, placeholder, type = "text", required = false, className = "" }) => (
                                <div key={label} className="flex flex-col gap-1">
                                    <label className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground">{label}</label>
                                    <input
                                        type={type}
                                        value={value}
                                        onChange={e => onChange(e.target.value)}
                                        placeholder={placeholder}
                                        required={required}
                                        className={`px-3 py-1.5 rounded-lg border border-border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary ${className}`}
                                    />
                                </div>
                            ))}
                            <div className="col-span-full flex justify-end gap-2 pt-2">
                                <button type="button" onClick={() => setShowForm(false)} className="px-3 py-1.5 rounded-lg text-sm text-muted-foreground hover:bg-muted transition-colors">
                                    Cancel
                                </button>
                                <button type="submit" disabled={submitting} className="px-4 py-1.5 rounded-lg bg-primary text-primary-foreground text-sm font-medium disabled:opacity-60 hover:bg-primary/90 transition-colors">
                                    {submitting ? "Saving…" : "Save"}
                                </button>
                            </div>
                        </motion.form>
                    )}
                </AnimatePresence>

                {/* Table */}
                {loading ? (
                    <div className="flex items-center justify-center h-40 text-muted-foreground text-sm">Loading…</div>
                ) : positions.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-48 gap-3 text-muted-foreground">
                        <AlertCircle className="h-10 w-10 opacity-20" />
                        <p className="text-sm">No positions yet. Add one or import a file.</p>
                    </div>
                ) : (
                    <div className="rounded-xl border border-border/60 overflow-hidden">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="border-b border-border/50 bg-muted/30">
                                    {["Symbol", "Qty", "Avg Cost", "Currency", "Account", "Date", "Source", ""].map(h => (
                                        <th key={h} className="text-left px-4 py-2.5 text-[10px] font-mono uppercase tracking-widest text-muted-foreground">
                                            {h}
                                        </th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody>
                                <AnimatePresence>
                                    {positions.map((p, i) => (
                                        <motion.tr
                                            key={`${p.symbol}-${p.account}-${p.date}`}
                                            initial={{ opacity: 0 }}
                                            animate={{ opacity: 1 }}
                                            exit={{ opacity: 0 }}
                                            transition={{ delay: i * 0.03 }}
                                            className="border-b border-border/30 hover:bg-muted/20 transition-colors"
                                        >
                                            <td className="px-4 py-3 font-mono font-bold text-primary">{p.symbol}</td>
                                            <td className="px-4 py-3 tabular-nums">{p.quantity.toLocaleString()}</td>
                                            <td className="px-4 py-3 tabular-nums">
                                                {p.cost_basis != null ? `$${p.cost_basis.toLocaleString(undefined, { minimumFractionDigits: 2 })}` : "—"}
                                            </td>
                                            <td className="px-4 py-3 text-muted-foreground font-mono text-xs">{p.currency}</td>
                                            <td className="px-4 py-3 text-muted-foreground">{p.account}</td>
                                            <td className="px-4 py-3 text-muted-foreground font-mono text-xs">{p.date}</td>
                                            <td className="px-4 py-3">
                                                <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-mono uppercase tracking-wider bg-muted text-muted-foreground">
                                                    {p.source}
                                                </span>
                                            </td>
                                            <td className="px-4 py-3">
                                                <button
                                                    onClick={() => handleDelete(p.symbol, p.account)}
                                                    className="p-1 rounded hover:bg-destructive/10 text-destructive/50 hover:text-destructive transition-colors"
                                                    title={`Remove ${p.symbol}`}
                                                >
                                                    <Trash2 className="h-3.5 w-3.5" />
                                                </button>
                                            </td>
                                        </motion.tr>
                                    ))}
                                </AnimatePresence>
                            </tbody>
                        </table>
                    </div>
                )}

                {/* AI Tip */}
                {positions.length > 0 && (
                    <p className="mt-3 text-[11px] text-muted-foreground text-center">
                        💡 Your portfolio context is automatically included in every AI response — ask <em>"What is my current risk exposure?"</em>
                    </p>
                )}
            </div>
        </div>
    );
}
