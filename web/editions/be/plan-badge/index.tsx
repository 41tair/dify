import { useTranslation } from 'react-i18next'
import { RiGraduationCapFill } from '@remixicon/react'
import PremiumBadge from '@/app/components/base/premium-badge'
import { Plan } from '@/app/components/billing/type'
import { useProviderContext } from '@/context/provider-context'
import { SparklesSoft } from '@/app/components/base/icons/src/public/common'
import type { PlanBadgeComponent } from '@/app/components/header/plan-badge/types'

/**
 * Enterprise Edition implementation of PlanBadge
 * Includes all plan types: sandbox, professional, team, enterprise
 */
const PlanBadgeBE: PlanBadgeComponent = ({ plan, allowHover, sandboxAsUpgrade = false, onClick }) => {
  const { isFetchedPlan, isEducationWorkspace } = useProviderContext()
  const { t } = useTranslation()

  if (!isFetchedPlan)
    return null

  // Sandbox with upgrade option
  if (plan === Plan.sandbox && sandboxAsUpgrade) {
    return (
      <PremiumBadge
        className='select-none'
        color='blue'
        allowHover={allowHover}
        onClick={onClick}
      >
        <SparklesSoft className='flex h-3.5 w-3.5 items-center py-[1px] pl-[3px] text-components-premium-badge-indigo-text-stop-0' />
        <div className='system-xs-medium'>
          <span className='whitespace-nowrap p-1'>
            {t('billing.upgradeBtn.encourageShort')}
          </span>
        </div>
      </PremiumBadge>
    )
  }

  // Standard sandbox plan
  if (plan === Plan.sandbox) {
    return (
      <PremiumBadge
        className='select-none'
        size='s'
        color='gray'
        allowHover={allowHover}
        onClick={onClick}
      >
        <div className='system-2xs-medium-uppercase'>
          <span className='p-1'>
            {plan}
          </span>
        </div>
      </PremiumBadge>
    )
  }

  // Professional plan
  if (plan === Plan.professional) {
    return (
      <PremiumBadge
        className='select-none'
        size='s'
        color='blue'
        allowHover={allowHover}
        onClick={onClick}
      >
        <div className='system-2xs-medium-uppercase'>
          <span className='inline-flex items-center gap-1 p-1'>
            {isEducationWorkspace && <RiGraduationCapFill className='h-3 w-3' />}
            pro
          </span>
        </div>
      </PremiumBadge>
    )
  }

  // Team plan
  if (plan === Plan.team) {
    return (
      <PremiumBadge
        className='select-none'
        size='s'
        color='indigo'
        allowHover={allowHover}
        onClick={onClick}
      >
        <div className='system-2xs-medium-uppercase'>
          <span className='p-1'>
            {plan}
          </span>
        </div>
      </PremiumBadge>
    )
  }

  // Enterprise plan - not displayed
  return null
}

export default PlanBadgeBE
