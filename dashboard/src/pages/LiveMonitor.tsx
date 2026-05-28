import { useState, useEffect, useRef } from 'react'
import { Card, CardContent, CardHeader, CardTitle, Badge } from '@/components/ui'
import { useWebSocket } from '@/hooks/useWebSocket'
import type { AgentLog, WebSocketMessage } from '@/lib/types'
import { formatTimestamp } from '@/lib/utils'
import { Wifi, WifiOff, ArrowDown } from 'lucide-react'

const WS_URL = `ws://${window.location.host}/ws`

const levelColors: Record<AgentLog['level'], string> = {
  info: 'text-blue-400',
  warn: 'text-yellow-400',
  error: 'text-red-400',
  debug: 'text-gray-400',
}

export default function LiveMonitor() {
  const [logs, setLogs] = useState<AgentLog[]>([])
  const [autoScroll, setAutoScroll] = useState(true)
  const logsEndRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const handleMessage = (msg: WebSocketMessage) => {
    if (msg.type === 'log') {
      setLogs((prev) => [...prev.slice(-499), msg.data])
    }
  }

  const { isConnected } = useWebSocket({ url: WS_URL, onMessage: handleMessage })

  useEffect(() => {
    if (autoScroll && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs, autoScroll])

  const handleScroll = () => {
    if (containerRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = containerRef.current
      setAutoScroll(scrollHeight - scrollTop - clientHeight < 50)
    }
  }

  return (
    <div className="flex flex-col h-full gap-4">
      <Card className="flex-shrink-0">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-cyan-500 animate-pulse" />
              Live Agent Logs
            </CardTitle>
            <div className="flex items-center gap-3">
              <Badge variant={autoScroll ? 'default' : 'secondary'} className="cursor-pointer" onClick={() => setAutoScroll(!autoScroll)}>
                <ArrowDown className="w-3 h-3 mr-1" />
                Auto-scroll
              </Badge>
              <Badge variant={isConnected ? 'default' : 'destructive'} className="gap-1">
                {isConnected ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
                {isConnected ? 'Connected' : 'Disconnected'}
              </Badge>
            </div>
          </div>
        </CardHeader>
      </Card>

      <Card className="flex-1 min-h-0">
        <CardContent className="p-0 h-full" ref={containerRef} onScroll={handleScroll}>
          <div className="font-mono text-sm h-full overflow-auto p-4 space-y-1">
            {logs.length === 0 ? (
              <div className="text-muted-foreground text-center py-8">Waiting for logs...</div>
            ) : (
              logs.map((log, i) => (
                <div key={`${log.id}-${i}`} className="flex gap-3 py-0.5 hover:bg-slate-900/50 px-2 rounded">
                  <span className="text-muted-foreground shrink-0">{formatTimestamp(new Date(log.timestamp))}</span>
                  <span className={cn('shrink-0 uppercase text-xs font-bold w-16', levelColors[log.level])}>{log.level}</span>
                  <span className="text-cyan-400 shrink-0 w-28">{log.agent}</span>
                  <span className="text-slate-300 break-all">{log.message}</span>
                </div>
              ))
            )}
            <div ref={logsEndRef} />
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function cn(...classes: (string | boolean | undefined)[]) {
  return classes.filter(Boolean).join(' ')
}
