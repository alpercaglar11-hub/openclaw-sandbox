import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui'
import { useWebSocket } from '@/hooks/useWebSocket'
import type { Metrics, WebSocketMessage } from '@/lib/types'
import { formatDuration } from '@/lib/utils'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts'

const WS_URL = `ws://${window.location.host}/ws`

const COLORS = ['#06b6d4', '#3b82f6', '#8b5cf6', '#ec4899', '#f59e0b']

const defaultMetrics: Metrics = {
  totalTasks: 0,
  completedTasks: 0,
  failedTasks: 0,
  averageDuration: 0,
  successRate: 100,
  tasksByAgent: {},
  errorsByType: {},
}

export default function MetricsPage() {
  const [metrics, setMetrics] = useState<Metrics>(defaultMetrics)

  const handleMessage = (msg: WebSocketMessage) => {
    if (msg.type === 'metrics') {
      setMetrics(msg.data)
    }
  }

  useWebSocket({ url: WS_URL, onMessage: handleMessage })

  const agentData = Object.entries(metrics.tasksByAgent).map(([name, count]) => ({ name, count }))
  const errorData = Object.entries(metrics.errorsByType).map(([type, count]) => ({ type, count }))
  const statusData = [
    { name: 'Completed', value: metrics.completedTasks },
    { name: 'Failed', value: metrics.failedTasks },
    { name: 'Pending', value: metrics.totalTasks - metrics.completedTasks - metrics.failedTasks },
  ].filter((d) => d.value > 0)

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">Total Tasks</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-3xl font-bold">{metrics.totalTasks}</div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">Success Rate</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-3xl font-bold">{metrics.successRate.toFixed(1)}%</div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">Avg Duration</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-3xl font-bold">{formatDuration(metrics.averageDuration)}</div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">Error Count</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-3xl font-bold text-red-500">{metrics.failedTasks}</div>
        </CardContent>
      </Card>

      <Card className="col-span-2">
        <CardHeader>
          <CardTitle className="text-sm">Tasks by Agent</CardTitle>
        </CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={agentData}>
              <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 12 }} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 12 }} />
              <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }} />
              <Bar dataKey="count" fill="#06b6d4" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      <Card className="col-span-2">
        <CardHeader>
          <CardTitle className="text-sm">Task Status Distribution</CardTitle>
        </CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={200}>
            <PieChart>
              <Pie data={statusData} cx="50%" cy="50%" innerRadius={50} outerRadius={80} dataKey="value" label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}>
                {statusData.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }} />
            </PieChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      {errorData.length > 0 && (
        <Card className="col-span-2">
          <CardHeader>
            <CardTitle className="text-sm">Errors by Type</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={errorData}>
                <XAxis dataKey="type" tick={{ fill: '#94a3b8', fontSize: 12 }} />
                <YAxis tick={{ fill: '#94a3b8', fontSize: 12 }} />
                <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }} />
                <Bar dataKey="count" fill="#ef4444" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
