import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle, Badge } from '@/components/ui'
import { useWebSocket } from '@/hooks/useWebSocket'
import type { AgentStatus, WebSocketMessage } from '@/lib/types'
import { formatTimestamp } from '@/lib/utils'
import { Heart, CheckCircle, XCircle, HelpCircle } from 'lucide-react'

const WS_URL = `ws://${window.location.host}/ws`

const statusIcons = {
  healthy: CheckCircle,
  unhealthy: XCircle,
  unknown: HelpCircle,
}

const statusColors = {
  healthy: 'text-green-500',
  unhealthy: 'text-red-500',
  unknown: 'text-yellow-500',
}

const defaultAgents: AgentStatus[] = [
  { id: 'hermes', name: 'HermesManager', status: 'unknown', lastHeartbeat: new Date().toISOString(), currentAction: 'Waiting...', tasksCompleted: 0, tasksFailed: 0 },
  { id: 'sandbox', name: 'SandboxWorker', status: 'unknown', lastHeartbeat: new Date().toISOString(), currentAction: 'Waiting...', tasksCompleted: 0, tasksFailed: 0 },
  { id: 'review', name: 'ReviewAgent', status: 'unknown', lastHeartbeat: new Date().toISOString(), currentAction: 'Waiting...', tasksCompleted: 0, tasksFailed: 0 },
  { id: 'observer', name: 'ObserverAgent', status: 'unknown', lastHeartbeat: new Date().toISOString(), currentAction: 'Waiting...', tasksCompleted: 0, tasksFailed: 0 },
]

export default function AgentStatusPage() {
  const [agents, setAgents] = useState<AgentStatus[]>(defaultAgents)

  const handleMessage = (msg: WebSocketMessage) => {
    if (msg.type === 'agent_status') {
      setAgents((prev) => {
        const idx = prev.findIndex((a) => a.id === msg.data.id)
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

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Heart className="w-5 h-5 text-red-500 animate-pulse" />
          Agent Health
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 md:grid-cols-2">
          {agents.map((agent) => {
            const Icon = statusIcons[agent.status]
            return (
              <div key={agent.id} className="p-4 rounded-lg border bg-card">
                <div className="flex items-start justify-between mb-3">
                  <div>
                    <div className="font-medium">{agent.name}</div>
                    <div className="flex items-center gap-1 text-sm text-muted-foreground mt-1">
                      <Icon className={cn('w-4 h-4', statusColors[agent.status])} />
                      <span className="capitalize">{agent.status}</span>
                    </div>
                  </div>
                  <Badge variant={agent.status === 'healthy' ? 'default' : agent.status === 'unhealthy' ? 'destructive' : 'secondary'}>
                    {agent.currentAction}
                  </Badge>
                </div>
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <div className="text-muted-foreground">Last Heartbeat</div>
                    <div className="font-mono mt-1">{formatTimestamp(new Date(agent.lastHeartbeat))}</div>
                  </div>
                  <div>
                    <div className="text-muted-foreground">Tasks</div>
                    <div className="mt-1">
                      <span className="text-green-500">{agent.tasksCompleted} done</span>
                      {agent.tasksFailed > 0 && <span className="text-red-500 ml-2">{agent.tasksFailed} failed</span>}
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}

function cn(...classes: (string | boolean | undefined)[]) {
  return classes.filter(Boolean).join(' ')
}
