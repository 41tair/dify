// This file demonstrates how to configure webpack in next.config.js
// to use module aliases for build-time switching

// Add this to your next.config.js webpack configuration:
/*
module.exports = {
  webpack: (config, { buildId, dev, isServer, defaultLoaders, webpack }) => {
    const edition = process.env.NEXT_PUBLIC_EDITION || 'SELF_HOSTED'
    const isEE = edition === 'ENTERPRISE' || edition === 'CLOUD'

    // Create aliases for EE/CE components
    config.resolve.alias = {
      ...config.resolve.alias,
      '@/components/header/plan-badge/impl': isEE
        ? '@/components/header/ee/plan-badge'
        : '@/components/header/plan-badge/ce'
    }

    return config
  }
}
*/

// Then in your index.tsx, you would simply do:
// import PlanBadge from './impl'
// export default PlanBadge