import { cn } from '@/lib/utils'
import { HTMLAttributes, forwardRef } from 'react'

const Badge = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement> & { variant?: 'default' | 'secondary' | 'destructive' | 'outline' }>(({ className, variant = 'default', ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      'inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-semibold transition-colors',
      {
        'bg-primary text-primary-foreground': variant === 'default',
        'bg-secondary text-secondary-foreground': variant === 'secondary',
        'bg-destructive text-destructive-foreground': variant === 'destructive',
        'text-foreground': variant === 'outline',
      },
      className
    )}
    {...props}
  />
))
Badge.displayName = 'Badge'

export { Badge }
