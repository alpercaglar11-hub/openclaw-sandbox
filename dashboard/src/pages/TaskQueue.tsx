import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle, Badge } from '@/components/ui'
import { useWebSocket } from '@/hooks/useWebSocket'
import type { Task, WebSocketMessage } from '@/lib/types'
import { formatDuration } from '@/lib/utils'
import { Clock, CheckCircle, XCircle, Loader2 } from 'lucide-react'

const WS_URL = `ws://${window.location.host}/ws`

const statusIcons = {
  pending: Clock,
  running: Loader2,
  completed: CheckCircle,
  failed: XCircle,
}

const statusColors = {
  pending: 'text-yellow-500',
  running: 'text-blue-500 animate-spin',
  completed: 'text-green-500',
  failed: 'text-red-500',
}

export default function TaskQueue() {
  const [tasks, setTasks] = useState<Task[]>([])

  const handleMessage = (msg: WebSocketMessage) => {
    if (msg.type === 'task') {
      setTasks((prev) => {
        const idx = prev.findIndex((t) => t.id === msg.data.id)
        if (idx >= 0) {
          const updated = [...prev]
          updated[idx] = msg.data
          return updated
        }
        return [...prev, msg.data]
      })
    }
  }

  useWebSocket({ url: WS_URL, onMessage: handleMessage })

  const sortedTasks = [...tasks].sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())

  const statusCounts = tasks.reduce(
    (acc, t) => {
      acc[t.status] = (acc[t.status] || 0) + 1
      return acc
    },
    {} as Record<string, number>
  )

  return (
    <Card className="h-full">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-cyan-500 animate-pulse" />
            Task Queue
          </CardTitle>
          <div className="flex gap-2">
            {Object.entries(statusCounts).map(([status, count]) => (
              <Badge key={status} variant="secondary" className="capitalize">
                {status}: {count}
              </Badge>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-2 overflow-auto max-h-[calc(100vh-280px)]">
          {sortedTasks.length === 0 ? (
            <div className="text-muted-foreground text-center py-8">No tasks yet</div>
          ) : (
            sortedTasks.map((task) => {
              const Icon = statusIcons[task.status]
              return (
                <div key={task.id} className="flex items-center gap-4 p-3 rounded-lg border bg-card hover:bg-slate-900/50">
                  <Icon className={cn('w-5 h-5 shrink-0', statusColors[task.status])} />
                  <div className="flex-1 min-w-0">
                    <div className="font-medium truncate">{task.name}</div>
                    <div className="text-sm text-muted-foreground">{task.agent}</div>
                  </div>
                  <Badge
                    variant={task.status === 'completed' ? 'default' : task.status === 'running' ? 'secondary' : task.status === 'failed' ? 'destructive' : 'outline'}
                    className="capitalize shrink-0"
                  >
                    {task.status}
                  </Badge>
                  {task.duration && (
                    <span className="text-sm text-muted-foreground shrink-0">{formatDuration(task.duration)}</span>
                  )}
                </div>
              )
            })
          )}
        </div>
      </CardContent>
    </Card>
  )
}

function cn(...classes: (string | boolean | undefined)[]) {
  return classes.filter(Boolean).join(' ')
}
