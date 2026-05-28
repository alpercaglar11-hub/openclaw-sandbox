import { useEffect, useRef, useState, useCallback } from 'react'
import type { WebSocketMessage } from '@/lib/types'

interface UseWebSocketOptions {
  url: string
  onMessage?: (msg: WebSocketMessage) => void
  reconnectInterval?: number
}

export function useWebSocket({ url, onMessage, reconnectInterval = 3000 }: UseWebSocketOptions) {
  const [isConnected, setIsConnected] = useState(false)
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const shouldReconnect = useRef(true)

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    try {
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => setIsConnected(true)

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data) as WebSocketMessage
          setLastMessage(msg)
          onMessage?.(msg)
        } catch {
          console.error('Failed to parse WebSocket message')
        }
      }

      ws.onerror = () => {
        setIsConnected(false)
      }

      ws.onclose = () => {
        setIsConnected(false)
        if (shouldReconnect.current) {
          reconnectTimerRef.current = setTimeout(connect, reconnectInterval)
        }
      }
    } catch {
      setIsConnected(false)
    }
  }, [url, onMessage, reconnectInterval])

  const disconnect = useCallback(() => {
    shouldReconnect.current = false
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current)
    }
    wsRef.current?.close()
  }, [])

  useEffect(() => {
    shouldReconnect.current = true
    connect()
    return () => {
      disconnect()
    }
  }, [connect, disconnect])

  const send = useCallback((data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data))
    }
  }, [])

  return { isConnected, lastMessage, send, disconnect, reconnect: connect }
}
