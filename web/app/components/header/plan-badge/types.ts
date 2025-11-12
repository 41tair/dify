import type { FC } from 'react'
import type { Plan } from '../../billing/type'

export type PlanBadgeProps = {
  plan: Plan
  allowHover?: boolean
  sandboxAsUpgrade?: boolean
  onClick?: () => void
}

export type PlanBadgeComponent = FC<PlanBadgeProps>

export interface PlanBadgeImplementation {
  component: PlanBadgeComponent
}