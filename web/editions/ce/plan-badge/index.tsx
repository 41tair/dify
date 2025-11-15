import type { PlanBadgeComponent } from '@/app/components/header/plan-badge/types'

/**
 * Community Edition implementation of PlanBadge
 * Only shows sandbox plan functionality
 */
const PlanBadgeCE: PlanBadgeComponent = ({}) => {
  return <span className='text-text-accent'>Community Badge</span>
}

export default PlanBadgeCE
