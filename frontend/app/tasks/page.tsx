"use client";

import { Suspense, useState, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { TaskList } from "@/components/tasks/task-list";
import { TaskDetail } from "@/components/tasks/task-detail";
import { useBacktests } from "@/lib/hooks";
import { Loader2, ListChecks } from "lucide-react";

export default function TasksPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-full items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      }
    >
      <TasksContent />
    </Suspense>
  );
}

function TasksContent() {
  const searchParams = useSearchParams();
  const { data, isLoading } = useBacktests();
  const [activeId, setActiveId] = useState<string | null>(null);

  useEffect(() => {
    const paramId = searchParams.get("active");
    if (paramId) {
      setActiveId(paramId);
    } else if (data?.items && data.items.length > 0 && !activeId) {
      setActiveId(data.items[0].id);
    }
  }, [searchParams, data, activeId]);

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  const tasks = data?.items || [];

  return (
    <div className="p-6">
      <div className="mb-6">
        <h2 className="text-xl font-semibold text-foreground">回测任务</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          管理回测任务，查看实时进度与日志
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[360px_1fr]">
        {/* Task List */}
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <ListChecks className="h-4 w-4" />
            <span>共 {tasks.length} 个任务</span>
          </div>
          <TaskList
            tasks={tasks}
            activeId={activeId}
            onSelect={setActiveId}
          />
        </div>

        {/* Task Detail */}
        <div>
          {activeId ? (
            <TaskDetail backtestId={activeId} />
          ) : (
            <div className="flex h-60 flex-col items-center justify-center text-muted-foreground">
              <ListChecks className="mb-2 h-8 w-8" />
              <p className="text-sm">选择一个任务查看详情</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
