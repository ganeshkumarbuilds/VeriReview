const AGENTS = [
  { key: 'plan', label: 'Plan', match: 'plan:', color: 'bg-violet-500' },
  { key: 'architect', label: 'Architect', match: 'architect:', color: 'bg-orange-500' },
  { key: 'build', label: 'Build / Coding Agent', match: 'build:', color: 'bg-green-500' },
  { key: 'test', label: 'Test', match: 'test:', color: 'bg-blue-500' },
  { key: 'verify', label: 'Verify', match: 'verify:', color: 'bg-emerald-500' },
  { key: 'review', label: 'Review', match: 'review:', color: 'bg-yellow-500' },
  { key: 'complete', label: 'Complete', match: 'complete:', color: 'bg-pink-500' },
]

function getStatuses(steps, loading) {
  const lowerSteps = steps.map(function (s) { return s.toLowerCase() })
  let activeIndex = -1

  for (let i = AGENTS.length - 1; i >= 0; i--) {
    if (lowerSteps.some(function (s) { return s.indexOf(AGENTS[i].match) !== -1 })) {
      activeIndex = i
      break
    }
  }

  // FAIL gate loops back to Build (Coding Agent FIX)
  const lastStep = lowerSteps[lowerSteps.length - 1] || ''
  if (lastStep.indexOf('sending back to coding agent') !== -1 || lastStep.indexOf('fail: review gate') !== -1) {
    activeIndex = 2
  }

  return AGENTS.map(function (agent, i) {
    let status = 'pending'
    if (i < activeIndex) status = 'completed'
    else if (i === activeIndex) status = loading ? 'working' : 'completed'
    return {
      key: agent.key,
      label: agent.label,
      color: agent.color,
      status: status,
      progress: status === 'completed' ? 100 : status === 'working' ? 60 : 0,
    }
  })
}

const statusText = {
  completed: 'Done',
  working: 'Running',
  pending: 'Waiting',
}

const statusColor = {
  completed: 'text-green-400',
  working: 'text-yellow-400',
  pending: 'text-gray-500',
}

export default function AgentStatusPanel(props) {
  const agents = getStatuses(props.steps, props.loading)

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
      {agents.map(function (agent) {
        return (
          <div key={agent.key} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
            <div className="flex items-center gap-2 mb-2">
              <span className={'w-2 h-2 rounded-full ' + agent.color}></span>
              <span className="font-semibold text-gray-100 text-sm">{agent.label}</span>
            </div>
            <div className={'text-xs font-medium mb-2 ' + statusColor[agent.status]}>
              {statusText[agent.status]}
            </div>
            <div className="w-full bg-gray-800 rounded-full h-1.5 overflow-hidden">
              <div
                className={'h-full ' + agent.color + ' transition-all duration-500'}
                style={{ width: agent.progress + '%' }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}
