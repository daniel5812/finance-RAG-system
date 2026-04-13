import { NavLink, Outlet } from "react-router-dom";
import { Activity, AlertTriangle, BarChart2, Home, List, Users } from "lucide-react";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/admin/overview",  label: "Overview",  icon: Home },
  { to: "/admin/requests",  label: "Requests",  icon: List },
  { to: "/admin/errors",    label: "Errors",    icon: AlertTriangle },
  { to: "/admin/metrics",   label: "Metrics",   icon: BarChart2 },
  { to: "/admin/users",     label: "Users",     icon: Users },
];

export function AdminLayout() {
  return (
    <div className="min-h-screen bg-gray-50 flex">
      {/* Sidebar */}
      <aside className="w-52 bg-gray-900 text-gray-100 flex flex-col flex-shrink-0">
        <div className="px-4 py-5 border-b border-gray-700">
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-indigo-400" />
            <span className="text-sm font-bold tracking-tight">Admin Console</span>
          </div>
          <div className="text-xs text-gray-500 mt-0.5">Investment Intelligence</div>
        </div>
        <nav className="flex-1 px-2 py-4 space-y-0.5">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2.5 px-3 py-2 rounded text-sm transition-colors",
                  isActive
                    ? "bg-indigo-600 text-white"
                    : "text-gray-400 hover:bg-gray-800 hover:text-white"
                )
              }
            >
              <Icon className="w-4 h-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="px-4 py-3 border-t border-gray-700">
          <NavLink to="/" className="text-xs text-gray-500 hover:text-gray-300">← Back to App</NavLink>
        </div>
      </aside>

      {/* Content */}
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
