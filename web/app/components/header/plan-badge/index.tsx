import type { PlanBadgeComponent } from './types'

// This file acts as a facade that re-exports the appropriate implementation
// The actual implementation is selected based on the NEXT_PUBLIC_EDITION environment variable

const edition = process.env.NEXT_PUBLIC_EDITION
const isEnterpriseEdition = edition === 'ENTERPRISE' || edition === 'CLOUD'

// Conditional require to avoid bundling both implementations
const PlanBadge: PlanBadgeComponent = isEnterpriseEdition
  ? require('../ee/plan-badge').default
  : require('./ce').default

export default PlanBadge
export type { PlanBadgeProps } from './types'