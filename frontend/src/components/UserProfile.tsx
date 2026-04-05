import { getUser, logout, User } from "@/lib/auth";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { LogOut, User as UserIcon, LayoutDashboard, TrendingUp, Shield } from "lucide-react";

interface UserProfileProps {
    onOpenSettings?: () => void;
}

export function UserProfile({ onOpenSettings }: UserProfileProps) {
    const [user, setUser] = useState<User | null>(null);
    const navigate = useNavigate();

    useEffect(() => {
        setUser(getUser());
    }, []);

    if (!user) return null;

    const isAdmin = user.role === "admin";

    const initials = user.name
        ? user.name.split(" ").map(n => n[0]).join("").toUpperCase()
        : user.email[0].toUpperCase();

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <button className="flex items-center gap-2 p-1 rounded-full hover:bg-muted transition-colors focus:outline-none">
                    <Avatar className="h-8 w-8 border border-border">
                        <AvatarFallback className={`text-xs font-bold ${isAdmin ? "bg-amber-500/20 text-amber-500" : "bg-primary/10 text-primary"}`}>
                            {initials}
                        </AvatarFallback>
                    </Avatar>
                </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56 mt-2 bg-background/95 backdrop-blur-sm border-border">
                <DropdownMenuLabel className="font-normal">
                    <div className="flex flex-col space-y-1">
                        <div className="flex items-center gap-2">
                            <p className="text-sm font-medium leading-none">{user.name || "User"}</p>
                            {isAdmin && (
                                <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-mono uppercase tracking-wider bg-amber-500/15 text-amber-500 border border-amber-500/20">
                                    <Shield className="h-2.5 w-2.5" />
                                    Admin
                                </span>
                            )}
                        </div>
                        <p className="text-xs leading-none text-muted-foreground">
                            {user.email}
                        </p>
                    </div>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem className="cursor-pointer" onClick={onOpenSettings}>
                    <UserIcon className="mr-2 h-4 w-4" />
                    <span>Profile Settings</span>
                </DropdownMenuItem>
                <DropdownMenuItem className="cursor-pointer" onClick={() => navigate("/portfolio")}>
                    <TrendingUp className="mr-2 h-4 w-4" />
                    <span>Portfolio</span>
                </DropdownMenuItem>
                {isAdmin && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem className="cursor-pointer text-amber-500 focus:text-amber-500" onClick={() => navigate("/admin")}>
                            <LayoutDashboard className="mr-2 h-4 w-4" />
                            <span>Admin Dashboard</span>
                        </DropdownMenuItem>
                    </>
                )}
                <DropdownMenuSeparator />
                <DropdownMenuItem
                    className="cursor-pointer text-destructive focus:text-destructive"
                    onClick={() => logout()}
                >
                    <LogOut className="mr-2 h-4 w-4" />
                    <span>Log out</span>
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    );
}

