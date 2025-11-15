import type { PlanBadgeComponent } from '@/app/components/header/plan-badge/types'

/**
 * Enterprise Edition implementation of PlanBadge
 * Includes all plan types: sandbox, professional, team, enterprise
 */
const PlanBadgeBE: PlanBadgeComponent = ({}) => {
  return <span className='text-text-accent'>Business Badge</span>
}

export default PlanBadgeBE
