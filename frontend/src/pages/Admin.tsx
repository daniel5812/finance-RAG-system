import { useState, useEffect } from "react";
import {
    Shield,
    Users,
    ClipboardList,
    Activity,
    Search,
    Filter,
    ChevronRight,
    ChevronLeft,
    AlertCircle,
    Database,
    UserCheck,
    UserX,
    History
} from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { authenticatedFetch } from "@/lib/api";
import { API_BASE } from "@/lib/api";

export default function Admin() {
    const [activeTab, setActiveTab] = useState("overview");

    return (
        <div className="flex flex-col h-screen bg-background overflow-hidden">
            <header className="h-16 border-b border-border flex items-center px-8 bg-muted/20 backdrop-blur-md sticky top-0 z-10 justify-between">
                <div className="flex items-center gap-3">
                    <div className="h-8 w-8 rounded-lg bg-primary/10 flex items-center justify-center">
                        <Shield className="h-5 w-5 text-primary" />
                    </div>
                    <div>
                        <h1 className="text-sm font-bold tracking-tight">Governance Console</h1>
                        <p className="text-[10px] text-muted-foreground uppercase font-mono tracking-widest leading-none">Production RBAC & Audit</p>
                    </div>
                </div>

                <Badge variant="outline" className="font-mono text-[10px] bg-emerald-500/10 text-emerald-500 border-emerald-500/20 px-2 py-0.5">
                    SYSTEM_READY
                </Badge>
            </header>

            <main className="flex-1 overflow-auto p-8 max-w-7xl mx-auto w-full">
                <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-8">
                    <TabsList className="bg-muted/50 p-1 border border-border/50 rounded-xl inline-flex h-auto">
                        <TabsTrigger value="overview" className="gap-2 px-6 py-2.5 rounded-lg data-[state=active]:bg-background data-[state=active]:shadow-sm">
                            <Activity className="h-4 w-4" />
                            <span>System Insights</span>
                        </TabsTrigger>
                        <TabsTrigger value="users" className="gap-2 px-6 py-2.5 rounded-lg data-[state=active]:bg-background data-[state=active]:shadow-sm">
                            <Users className="h-4 w-4" />
                            <span>Identity Management</span>
                        </TabsTrigger>
                        <TabsTrigger value="audit" className="gap-2 px-6 py-2.5 rounded-lg data-[state=active]:bg-background data-[state=active]:shadow-sm">
                            <ClipboardList className="h-4 w-4" />
                            <span>Audit Trail</span>
                        </TabsTrigger>
                    </TabsList>

                    <TabsContent value="overview" className="mt-0 outline-none">
                        <OverviewTab />
                    </TabsContent>
                    <TabsContent value="users" className="mt-0 outline-none">
                        <UsersTab />
                    </TabsContent>
                    <TabsContent value="audit" className="mt-0 outline-none">
                        <AuditTab />
                    </TabsContent>
                </Tabs>
            </main>
        </div>
    );
}

function OverviewTab() {
    const [stats, setStats] = useState<any>(null);

    useEffect(() => {
        const fetchStats = async () => {
            try {
                const res = await authenticatedFetch(`${API_BASE}/admin/metrics/summary`);
                if (res.ok) setStats(await res.json());
            } catch (err) { console.error(err); }
        };
        fetchStats();
        const interval = setInterval(fetchStats, 15000);
        return () => clearInterval(interval);
    }, []);

    if (!stats) return <div className="h-64 flex items-center justify-center animate-pulse text-muted-foreground text-xs font-mono">CALCULATING_SYSTEM_LOAD...</div>;

    return (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <Card className="bg-muted/10 border-border/50 hover:border-primary/20 transition-all shadow-none">
                <CardHeader className="pb-2">
                    <CardDescription className="text-[10px] uppercase font-mono tracking-widest text-muted-foreground">Throughput</CardDescription>
                    <CardTitle className="text-3xl font-bold tracking-tighter">{stats.throughput.total_queries}</CardTitle>
                </CardHeader>
                <CardContent>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <History className="h-3 w-3" />
                        <span>Cumulative Requests</span>
                    </div>
                </CardContent>
            </Card>

            <Card className="bg-muted/10 border-border/50 hover:border-primary/20 transition-all shadow-none">
                <CardHeader className="pb-2">
                    <CardDescription className="text-[10px] uppercase font-mono tracking-widest text-muted-foreground">User Efficiency (Cache)</CardDescription>
                    <CardTitle className="text-3xl font-bold tracking-tighter">{(stats.throughput.cache_hit_rate * 100).toFixed(1)}%</CardTitle>
                </CardHeader>
                <CardContent>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <Database className="h-3 w-3" />
                        <span>Retrieval Optimization Rate</span>
                    </div>
                </CardContent>
            </Card>

            <Card className="bg-muted/10 border-border/50 hover:border-primary/20 transition-all shadow-none">
                <CardHeader className="pb-2">
                    <CardDescription className="text-[10px] uppercase font-mono tracking-widest text-muted-foreground">p95 Response Latency</CardDescription>
                    <CardTitle className="text-3xl font-bold tracking-tighter">{stats.performance.p95}s</CardTitle>
                </CardHeader>
                <CardContent>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <Activity className="h-3 w-3" />
                        <span>Service Stability Indicator</span>
                    </div>
                </CardContent>
            </Card>

            <div className="md:col-span-3 mt-8">
                <h3 className="text-xs font-mono uppercase tracking-widest text-muted-foreground mb-4">Infrastructure Health</h3>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    {["LLM_GENERATION", "VECTOR_SEARCH", "SQL_ENGINE", "AUTH_LAYER"].map((sys) => (
                        <div key={sys} className="p-3 border border-border/50 rounded-lg bg-muted/5 flex items-center justify-between">
                            <span className="text-[10px] font-mono text-muted-foreground">{sys}</span>
                            <div className="h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)] anim-pulse shadow-emerald-500/50" />
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}

function UsersTab() {
    const [users, setUsers] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchUsers = async () => {
            try {
                const res = await authenticatedFetch(`${API_BASE}/admin/users`);
                if (res.ok) setUsers(await res.json());
            } catch (err) { console.error(err); }
            finally { setLoading(false); }
        };
        fetchUsers();
    }, []);

    return (
        <Card className="bg-muted/10 border-border/50 shadow-none border-none">
            <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-3">
                    <div className="relative">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                        <Input placeholder="Search identity..." className="h-9 w-[300px] pl-9 text-xs border-border/50 bg-background/50 focus:bg-background" />
                    </div>
                    <Button variant="outline" size="sm" className="h-9 gap-2 text-xs border-border/50">
                        <Filter className="h-3 w-3" />
                        Filters
                    </Button>
                </div>
            </div>

            <div className="rounded-xl border border-border/50 bg-background overflow-hidden relative">
                <table className="w-full text-left text-xs">
                    <thead className="bg-muted/30 border-b border-border/50">
                        <tr>
                            <th className="px-6 py-4 font-semibold text-muted-foreground uppercase tracking-widest text-[9px]">User Identity</th>
                            <th className="px-6 py-4 font-semibold text-muted-foreground uppercase tracking-widest text-[9px]">Assigned Role</th>
                            <th className="px-6 py-4 font-semibold text-muted-foreground uppercase tracking-widest text-[9px]">Permissions</th>
                            <th className="px-6 py-4 font-semibold text-muted-foreground uppercase tracking-widest text-[9px]">Onboarded</th>
                            <th className="px-6 py-4 font-semibold text-muted-foreground uppercase tracking-widest text-[9px] text-right">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {users.map((u) => (
                            <tr key={u.id} className="border-b border-border/50 hover:bg-muted/10 transition-colors group">
                                <td className="px-6 py-4">
                                    <div className="flex flex-col">
                                        <span className="font-bold text-foreground">{u.full_name || "Unknown Identity"}</span>
                                        <span className="text-[10px] text-muted-foreground font-mono">{u.email}</span>
                                    </div>
                                </td>
                                <td className="px-6 py-4">
                                    <Badge variant={u.role === 'admin' ? 'default' : 'secondary'} className="rounded-md text-[10px] h-5">
                                        {u.role.toUpperCase()}
                                    </Badge>
                                </td>
                                <td className="px-6 py-4">
                                    <div className="flex flex-wrap gap-1 max-w-[200px]">
                                        {u.scopes?.slice(0, 3).map((s: string) => (
                                            <span key={s} className="px-1.5 py-0.5 rounded bg-muted text-[8px] font-mono text-muted-foreground lowercase">{s}</span>
                                        ))}
                                        {u.scopes?.length > 3 && <span className="text-[8px] text-muted-foreground">+{u.scopes.length - 3} more</span>}
                                    </div>
                                </td>
                                <td className="px-6 py-4 text-muted-foreground">
                                    {new Date(u.created_at).toLocaleDateString()}
                                </td>
                                <td className="px-6 py-4 text-right opacity-0 group-hover:opacity-100 transition-opacity">
                                    <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-foreground">
                                        <ChevronRight className="h-4 w-4" />
                                    </Button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                {loading && <div className="absolute inset-0 bg-background/50 backdrop-blur-[1px] flex items-center justify-center font-mono text-[10px]">SYNC_IDENTITY_STORE...</div>}
            </div>
        </Card>
    );
}

function AuditTab() {
    const [events, setEvents] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchAudit = async () => {
            try {
                const res = await authenticatedFetch(`${API_BASE}/admin/audit-events`);
                if (res.ok) setEvents(await res.json());
            } catch (err) { console.error(err); }
            finally { setLoading(false); }
        };
        fetchAudit();
    }, []);

    return (
        <div className="space-y-6">
            <div className="flex items-center gap-4">
                <Badge variant="outline" className="gap-2 px-3 py-1 font-mono text-[10px] text-muted-foreground bg-muted/20 border-border/50">
                    <AlertCircle className="h-3 w-3" />
                    AUDIT_RETENTION: 90_DAYS
                </Badge>
                <p className="text-[10px] text-muted-foreground italic">
                    Metadata-only tracking. Raw content redacted to maintain tenant isolation and data privacy.
                </p>
            </div>

            <div className="space-y-3">
                {events.map((ev) => (
                    <div key={ev.id} className="p-4 border border-border/50 rounded-xl bg-background hover:border-primary/20 transition-all flex items-start gap-5">
                        <div className={`mt-0.5 h-8 w-8 rounded-lg flex items-center justify-center shrink-0 ${ev.event_type === 'login' ? 'bg-blue-500/10 text-blue-500' :
                                ev.event_type === 'admin_action' ? 'bg-amber-500/10 text-amber-500' :
                                    ev.event_type === 'error' ? 'bg-destructive/10 text-destructive' :
                                        'bg-emerald-500/10 text-emerald-500'
                            }`}>
                            {ev.event_type === 'login' ? <KeyIcon className="h-4 w-4" /> :
                                ev.event_type === 'admin_action' ? <Shield className="h-4 w-4" /> :
                                    ev.event_type === 'error' ? <AlertCircle className="h-4 w-4" /> :
                                        <Activity className="h-4 w-4" />}
                        </div>

                        <div className="flex-1 min-w-0">
                            <div className="flex items-center justify-between mb-1">
                                <div className="flex items-center gap-2">
                                    <span className="text-xs font-bold uppercase tracking-tight">{ev.event_type}</span>
                                    <span className="text-xs text-muted-foreground">/</span>
                                    <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${ev.status === 'success' ? 'bg-emerald-500/5 text-emerald-500 border-emerald-500/10' : 'bg-destructive/5 text-destructive border-destructive/10'
                                        }`}>
                                        {ev.status.toUpperCase()}
                                    </span>
                                </div>
                                <span className="text-[10px] text-muted-foreground font-mono">{new Date(ev.timestamp).toLocaleString()}</span>
                            </div>

                            <p className="text-xs text-foreground mb-3 leading-relaxed">
                                Identity <span className="font-mono bg-muted px-1 py-0.5 rounded italic text-[11px]">{ev.user_id?.substring(0, 8)}...</span> performed
                                <span className="mx-1.5 font-semibold text-primary underline underline-offset-4 decoration-primary/30">{ev.action}</span>
                                on {ev.resource_id ? `resource ${ev.resource_id}` : 'the system'}
                            </p>

                            <div className="p-2.5 rounded-lg bg-muted/30 border border-border/50 flex flex-wrap gap-4">
                                {Object.entries(ev.metadata || {}).map(([key, val]: [string, any]) => (
                                    <div key={key} className="flex items-center gap-2">
                                        <span className="text-[9px] font-mono text-muted-foreground lowercase">{key}:</span>
                                        <span className="text-[10px] font-medium">{String(val)}</span>
                                    </div>
                                ))}
                                <div className="ml-auto flex items-center gap-2 border-l border-border/50 pl-4">
                                    <span className="text-[9px] font-mono text-muted-foreground uppercase tracking-tighter">REQ_ID:</span>
                                    <span className="text-[9px] font-mono">{ev.request_id || "N/A"}</span>
                                </div>
                            </div>
                        </div>
                    </div>
                ))}
                {loading && <div className="h-32 flex items-center justify-center font-mono text-xs animate-pulse opacity-50">STREAMING_AUDIT_LOG_PACKETS...</div>}
            </div>
        </div>
    );
}

function KeyIcon({ className }: { className?: string }) {
    return (
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
            <circle cx="7.5" cy="15.5" r="5.5" />
            <path d="m21 2-9.6 9.6" />
            <path d="m15.5 7.5 3 3L22 7l-3-3" />
        </svg>
    );
}
