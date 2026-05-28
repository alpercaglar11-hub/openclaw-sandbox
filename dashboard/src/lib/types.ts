export interface AgentLog {
  id: string
  timestamp: string
  agent: string
  level: 'info' | 'warn' | 'error' | 'debug'
  message: string
  data?: Record<string, unknown>
}

export interface Task {
  id: string
  name: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  agent: string
  createdAt: string
  startedAt?: string
  completedAt?: string
  duration?: number
  error?: string
}

export interface AgentStatus {
  id: string
  name: string
  status: 'healthy' | 'unhealthy' | 'unknown'
  lastHeartbeat: string
  currentAction: string
  tasksCompleted: number
  tasksFailed: number
}

export interface Metrics {
  totalTasks: number
  completedTasks: number
  failedTasks: number
  averageDuration: number
  successRate: number
  tasksByAgent: Record<string, number>
  errorsByType: Record<string, number>
}

export interface ExecutionNode {
  id: string
  label: string
  type: 'manager' | 'worker' | 'agent'
  status: 'idle' | 'running' | 'completed' | 'failed'
}

export interface ExecutionEdge {
  from: string
  to: string
}

export interface ExecutionGraph {
  nodes: ExecutionNode[]
  edges: ExecutionEdge[]
}

export type WebSocketMessage =
  | { type: 'log'; data: AgentLog }
  | { type: 'task'; data: Task }
  | { type: 'agent_status'; data: AgentStatus }
  | { type: 'metrics'; data: Metrics }
  | { type: 'execution_graph'; data: ExecutionGraph }
  | { type: 'heartbeat'; data: { timestamp: string } }
