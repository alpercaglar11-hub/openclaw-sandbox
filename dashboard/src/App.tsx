import { useState, useEffect } from 'react'
import { Activity, LayoutDashboard, GitBranch, ListTodo, BarChart3, Heart, Clock } from 'lucide-react'
import LiveMonitor from './pages/LiveMonitor'
import ExecutionGraph from './pages/ExecutionGraph'
import TaskQueue from './pages/TaskQueue'
import Metrics from './pages/Metrics'
import AgentStatus from './pages/AgentStatus'

type Tab = 'live-monitor' | 'execution-graph' | 'task-queue' | 'metrics' | 'agent-status'

const tabs: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: 'live-monitor', label: 'Live Monitor', icon: Activity },
  { id: 'execution-graph', label: 'Execution Graph', icon: GitBranch },
  { id: 'task-queue', label: 'Task Queue', icon: ListTodo },
  { id: 'metrics', label: 'Metrics', icon: BarChart3 },
  { id: 'agent-status', label: 'Agent Status', icon: Heart },
]

function App() {
  const [activeTab, setActiveTab] = useState<Tab>('live-monitor')
  const [time, setTime] = useState(new Date())

  useEffect(() => {
    const interval = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(interval)
  }, [])

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      {/* Header */}
      <header className="border-b bg-slate-900/50 backdrop-blur-sm sticky top-0 z-50">
        <div className="container mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center font-bold">
              OC
            </div>
            <div>
              <h1 className="font-semibold text-lg">OpenClaw Dashboard</h1>
              <p className="text-xs text-muted-foreground">Real-time Agent Monitoring</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Clock className="w-4 h-4" />
              <span className="font-mono">{time.toLocaleTimeString()}</span>
            </div>
            <div className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
              <span className="text-xs text-muted-foreground">System Active</span>
            </div>
          </div>
        </div>
      </header>

      {/* Navigation */}
      <nav className="border-b bg-slate-900/30">
        <div className="container mx-auto px-4 flex gap-1">
          {tabs.map((tab) => {
            const Icon = tab.icon
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2 px-4 py-3 text-sm font-medium transition-colors relative ${
                  activeTab === tab.id
                    ? 'text-cyan-400'
                    : 'text-muted-foreground hover:text-slate-300'
                }`}
              >
                <Icon className="w-4 h-4" />
                {tab.label}
                {activeTab === tab.id && (
                  <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-cyan-500" />
                )}
              </button>
            )
          })}
        </div>
      </nav>

      {/* Main Content */}
      <main className="flex-1 container mx-auto px-4 py-6">
        <div className="h-[calc(100vh-180px)]">
          {activeTab === 'live-monitor' && <LiveMonitor />}
          {activeTab === 'execution-graph' && <ExecutionGraph />}
          {activeTab === 'task-queue' && <TaskQueue />}
          {activeTab === 'metrics' && <Metrics />}
          {activeTab === 'agent-status' && <AgentStatus />}
        </div>
      </main>
    </div>
  )
}

export default App
