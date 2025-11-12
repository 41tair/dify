import { useTranslation } from 'react-i18next'
import PremiumBadge from '../../base/premium-badge'
import { Plan } from '../../billing/type'
import { useProviderContext } from '@/context/provider-context'
import { SparklesSoft } from '../../base/icons/src/public/common'
import type { PlanBadgeComponent } from './types'

/**
 * Community Edition implementation of PlanBadge
 * Only shows sandbox plan functionality
 */
const PlanBadgeCE: PlanBadgeComponent = ({ plan, allowHover, sandboxAsUpgrade = false, onClick }) => {
  const { isFetchedPlan } = useProviderContext()
  const { t } = useTranslation()

  if (!isFetchedPlan)
    return null

  // Only handle sandbox plan in CE
  if (plan !== Plan.sandbox)
    return null

  // Sandbox with upgrade option
  if (sandboxAsUpgrade) {
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

export default PlanBadgeCE