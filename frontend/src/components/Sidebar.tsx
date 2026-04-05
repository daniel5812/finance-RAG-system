import { useState } from "react";
import { ChatSession, UploadedDocument } from "@/lib/api";
import { useNavigate } from "react-router-dom";
import {
    MessageSquare,
    Files,
    Plus,
    Trash2,
    ChevronLeft,
    ChevronRight,
    Clock,
    Activity,
    ShieldAlert,
    TrendingUp,
    Lightbulb
} from "lucide-react";


import { DocumentSidebar } from "./DocumentSidebar";
import { MetricsModal } from "./MetricsModal";
import { getUser } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { useInsights } from "@/lib/insights";
import type { Folder } from "@/lib/api";



interface SidebarProps {
    sessions: ChatSession[];
    activeSessionId: string | null;
    onSessionSelect: (id: string) => void;
    onNewChat: () => void;
    onDeleteSession: (id: string) => void;
    documents: UploadedDocument[];
    onDocumentUploaded: (doc: UploadedDocument) => void;
    onDocumentStatusChange: (id: string, status: UploadedDocument["status"]) => void;
    onDocumentDelete: (id: string) => void;
    collapsed: boolean;
    onToggleCollapse: () => void;
    selectedDocumentIds: string[];
    onToggleDocumentSelection: (id: string) => void;
    folders: Folder[];
    activeFolderId: number | null;
    onFolderSelect: (id: number | null) => void;
    onFolderCreate: (name: string) => void;
    onFolderDelete: (id: number) => void;
    onAssignFolder: (docId: string, folderId: number | null) => void;
}

export function Sidebar({
    sessions,
    activeSessionId,
    onSessionSelect,
    onNewChat,
    onDeleteSession,
    documents,
    onDocumentUploaded,
    onDocumentStatusChange,
    onDocumentDelete,
    collapsed,
    onToggleCollapse,
    selectedDocumentIds,
    onToggleDocumentSelection,
    folders,
    activeFolderId,
    onFolderSelect,
    onFolderCreate,
    onFolderDelete,
    onAssignFolder,
}: SidebarProps) {
    const [activeTab, setActiveTab] = useState<"chats" | "docs">("chats");
    const [showMetrics, setShowMetrics] = useState(false);
    const navigate = useNavigate();
    const user = getUser();
    const hasAdminScope = user?.scopes?.includes("admin:read") || user?.role === "admin";
    const { hasNewInsights } = useInsights();



    return (
        <div
            className={cn(
                "flex flex-col border-r border-border bg-card transition-all duration-300 ease-in-out",
                collapsed ? "w-16" : "w-72"
            )}
        >
            {/* Sidebar Header */}
            <div className="p-4 flex items-center justify-between border-b border-border/50">
                {!collapsed && (
                    <button
                        onClick={onNewChat}
                        className="flex-1 flex items-center justify-center gap-2 px-3 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:opacity-90 transition-all active:scale-95 shadow-sm"
                    >
                        <Plus className="h-4 w-4" />
                        <span>New Chat</span>
                    </button>
                )}
                <button
                    onClick={onToggleCollapse}
                    className={cn(
                        "p-2 rounded-md hover:bg-muted text-muted-foreground transition-colors",
                        collapsed ? "w-full flex justify-center" : "ml-2"
                    )}
                >
                    {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
                </button>
            </div>

            {/* Tab Switcher */}
            {!collapsed && (
                <div className="flex p-1 m-4 mb-2 bg-muted/50 rounded-lg border border-border/50">
                    <button
                        onClick={() => setActiveTab("chats")}
                        className={cn(
                            "flex-1 flex items-center justify-center gap-2 py-1.5 text-xs font-medium rounded-md transition-all",
                            activeTab === "chats" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                        )}
                    >
                        <MessageSquare className="h-3.5 w-3.5" />
                        Chats
                    </button>
                    <button
                        onClick={() => setActiveTab("docs")}
                        className={cn(
                            "flex-1 flex items-center justify-center gap-2 py-1.5 text-xs font-medium rounded-md transition-all",
                            activeTab === "docs" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                        )}
                    >
                        <Files className="h-3.5 w-3.5" />
                        Sources
                    </button>
                </div>
            )}

            {/* Sidebar Content */}
            <div className="flex-1 overflow-y-auto overflow-x-hidden pt-2 scroll-stable">
                {collapsed ? (
                    <div className="flex flex-col items-center gap-4 pt-4">
                        <button onClick={onNewChat} className="p-2 rounded-lg bg-primary text-primary-foreground hover:opacity-90 transition-all" title="New Chat">
                            <Plus className="h-5 w-5" />
                        </button>
                        <button onClick={() => setActiveTab("chats")} className={cn("p-2 rounded-lg transition-all", activeTab === "chats" ? "bg-muted text-primary" : "text-muted-foreground")} title="Chat History">
                            <MessageSquare className="h-5 w-5" />
                        </button>
                        <button onClick={() => setActiveTab("docs")} className={cn("p-2 rounded-lg transition-all", activeTab === "docs" ? "bg-muted text-primary" : "text-muted-foreground")} title="Document Sources">
                            <Files className="h-5 w-5" />
                        </button>
                        <button onClick={() => navigate('/insights')} className="relative p-2 rounded-lg text-muted-foreground hover:bg-muted transition-all" title="Insights">
                            <Lightbulb className="h-5 w-5" />
                            {hasNewInsights && (
                                <span className="absolute top-1 right-1 h-2 w-2 rounded-full bg-primary" />
                            )}
                        </button>
                    </div>
                ) : (
                    activeTab === "chats" ? (
                        <div className="px-3 space-y-1 pb-4">
                            <div className="px-2 mb-2">
                                <span className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground/60 flex items-center gap-2">
                                    <Clock className="h-3 w-3" />
                                    Recent History
                                </span>
                            </div>
                            {(!Array.isArray(sessions) || sessions.length === 0) ? (
                                <div className="px-2 py-8 text-center">
                                    <p className="text-xs text-muted-foreground italic">No conversations yet.</p>
                                </div>
                            ) : (
                                sessions.map((session) => (
                                    <div
                                        key={session.id}
                                        className={cn(
                                            "group relative flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer transition-all border border-transparent",
                                            activeSessionId === session.id
                                                ? "bg-primary/5 border-primary/10 text-primary"
                                                : "hover:bg-muted/50 text-muted-foreground hover:text-foreground"
                                        )}
                                        onClick={() => onSessionSelect(session.id)}
                                    >
                                        <MessageSquare className={cn("h-4 w-4 shrink-0", activeSessionId === session.id ? "text-primary" : "text-muted-foreground/50")} />
                                        <span className="text-sm truncate pr-6">{session.title}</span>
                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                onDeleteSession(session.id);
                                            }}
                                            className="absolute right-2 opacity-0 group-hover:opacity-100 p-1 text-muted-foreground hover:text-destructive transition-all"
                                            title="Delete Chat"
                                        >
                                            <Trash2 className="h-3.5 w-3.5" />
                                        </button>
                                    </div>
                                ))
                            )}
                        </div>
                    ) : (
                        <div className="px-3">
                            <DocumentSidebar
                                documents={documents}
                                onDocumentUploaded={onDocumentUploaded}
                                onDocumentStatusChange={onDocumentStatusChange}
                                onDocumentDelete={onDocumentDelete}
                                collapsed={false}
                                onToggleCollapse={() => { }}
                                isInsideSidebar
                                selectedIds={selectedDocumentIds}
                                onToggleSelection={onToggleDocumentSelection}
                                folders={folders}
                                activeFolderId={activeFolderId}
                                onFolderSelect={onFolderSelect}
                                onFolderCreate={onFolderCreate}
                                onFolderDelete={onFolderDelete}
                                onAssignFolder={onAssignFolder}
                            />
                        </div>
                    )
                )}
            </div>

            {/* Sidebar Footer */}
            {!collapsed && (
                <div className="p-4 border-t border-border/50 space-y-2">
                    {hasAdminScope && (
                        <button
                            onClick={() => navigate('/admin')}
                            className="w-full flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground transition-all group"
                        >
                            <ShieldAlert className="h-4 w-4 text-amber-500 group-hover:animate-pulse" />
                            <span className="text-xs font-medium">Admin Console</span>
                        </button>
                    )}

                    <button
                        onClick={() => navigate('/insights')}
                        className="w-full flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground transition-all group"
                    >
                        <div className="relative">
                            <Lightbulb className="h-4 w-4 text-primary group-hover:animate-pulse" />
                            {hasNewInsights && (
                                <span className="absolute -top-1 -right-1 h-2 w-2 rounded-full bg-primary" />
                            )}
                        </div>
                        <span className="text-xs font-medium">Insights</span>
                    </button>

                    <button
                        onClick={() => navigate('/portfolio')}
                        className="w-full flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground transition-all group"
                    >
                        <TrendingUp className="h-4 w-4 text-primary group-hover:animate-pulse" />
                        <span className="text-xs font-medium">Portfolio</span>
                    </button>

                    <button
                        onClick={() => setShowMetrics(true)}
                        className="w-full flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground transition-all group"
                    >
                        <Activity className="h-4 w-4 text-primary group-hover:animate-pulse" />
                        <span className="text-xs font-medium">System Status</span>
                    </button>


                    <div className="flex items-center gap-3 px-3 py-2 rounded-lg bg-muted/30">
                        <div className="h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center text-primary font-bold text-xs">
                            AD
                        </div>
                        <div className="flex-1 min-w-0">
                            <p className="text-xs font-semibold truncate">Advisor</p>
                            <p className="text-[10px] text-muted-foreground truncate">Free Tier</p>
                        </div>
                    </div>
                </div>
            )}

            <MetricsModal
                isOpen={showMetrics}
                onClose={() => setShowMetrics(false)}
            />
        </div>

    );
}
