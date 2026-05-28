import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle, Badge } from '@/components/ui'
import { useWebSocket } from '@/hooks/useWebSocket'
import type { ExecutionGraph, WebSocketMessage } from '@/lib/types'

const WS_URL = `ws://${window.location.host}/ws`

const nodeColors: Record<string, string> = {
  manager: 'bg-purple-600',
  worker: 'bg-blue-600',
  agent: 'bg-cyan-600',
}

const statusColors: Record<string, string> = {
  idle: 'bg-gray-600',
  running: 'bg-green-600 animate-pulse',
  completed: 'bg-emerald-600',
  failed: 'bg-red-600',
}

export default function ExecutionGraphView() {
  const [graph, setGraph] = useState<ExecutionGraph | null>(null)

  const handleMessage = (msg: WebSocketMessage) => {
    if (msg.type === 'execution_graph') {
      setGraph(msg.data)
    }
  }

  useWebSocket({ url: WS_URL, onMessage: handleMessage })

  const nodes = graph?.nodes ?? [
    { id: 'hermes', label: 'HermesManager', type: 'manager', status: 'idle' },
    { id: 'sandbox', label: 'SandboxWorker', type: 'worker', status: 'idle' },
    { id: 'review', label: 'ReviewAgent', type: 'agent', status: 'idle' },
    { id: 'observer', label: 'ObserverAgent', type: 'agent', status: 'idle' },
  ]

  const edges = graph?.edges ?? [
    { from: 'hermes', to: 'sandbox' },
    { from: 'sandbox', to: 'review' },
    { from: 'review', to: 'observer' },
  ]

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-cyan-500 animate-pulse" />
          Execution Flow
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-6 py-4">
          {nodes.map((node, i) => (
            <div key={node.id} className="relative">
              {i > 0 && (
                <div className="absolute -top-6 left-6 text-muted-foreground">
                  <svg className="w-4 h-6" viewBox="0 0 16 24">
                    <path d="M8 0v20M4 16l4 4 4-4" stroke="currentColor" strokeWidth="2" fill="none" />
                  </svg>
                </div>
              )}
              <div className="flex items-center gap-4 p-4 rounded-lg border bg-card">
                <div className={cn('w-4 h-4 rounded-full', nodeColors[node.type], statusColors[node.status])} />
                <div className="flex-1">
                  <div className="font-medium">{node.label}</div>
                  <div className="text-sm text-muted-foreground capitalize">{node.type}</div>
                </div>
                <Badge
                  variant={
                    node.status === 'completed' ? 'default' : node.status === 'running' ? 'secondary' : node.status === 'failed' ? 'destructive' : 'outline'
                  }
                  className="capitalize"
                >
                  {node.status}
                </Badge>
              </div>
              {edges.filter((e) => e.from === node.id).map((edge) => (
                <div key={`${edge.from}-${edge.to}`} className="ml-6 mt-2 pl-4 border-l-2 border-cyan-900">
                  <span className="text-xs text-muted-foreground ml-4">→ {nodes.find((n) => n.id === edge.to)?.label}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

function cn(...classes: (string | boolean | undefined)[]) {
  return classes.filter(Boolean).join(' ')
}
