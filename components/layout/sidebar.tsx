"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Settings2,
  ListTodo,
  Trophy,
  BookOpen,
  TrendingUp,
} from "lucide-react";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/backtest", label: "参数配置", icon: Settings2 },
  { href: "/tasks", label: "任务中心", icon: ListTodo },
  { href: "/rankings", label: "策略排名", icon: Trophy },
  { href: "/strategies", label: "策略介绍", icon: BookOpen },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed inset-y-0 left-0 z-40 flex w-60 flex-col border-r bg-card">
      <div className="flex h-16 items-center gap-2 border-b px-6">
        <TrendingUp className="h-6 w-6 text-primary" />
        <span className="text-lg font-bold text-foreground">Z哥回测系统</span>
      </div>
      <nav className="flex flex-1 flex-col gap-1 p-3">
        {navItems.map((item) => {
          const isActive =
            pathname === item.href || pathname.startsWith(item.href + "/");
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                isActive
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
              )}
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="border-t p-4">
        <p className="text-xs text-muted-foreground">
          {"Z哥战法 v1.0"}
        </p>
      </div>
    </aside>
  );
}
