export const NODES = [
  { key: 'plan', label: 'Plan', match: 'PLAN:', role: 'plan' },
  { key: 'architect', label: 'Architect', match: 'ARCHITECT:', role: 'plan' },
  { key: 'build', label: 'Build', match: 'BUILD:', role: 'build' },
  { key: 'test', label: 'Test', match: 'TEST:', role: 'build' },
  { key: 'verify', label: 'Verify', match: 'VERIFY:', role: 'verify' },
  { key: 'review', label: 'Review', match: 'REVIEW:', role: 'review' },
  { key: 'complete', label: 'Complete', match: 'COMPLETE:', role: 'verify' },
]

export function getActiveIndex(steps) {
  if (!steps.length) return -1
  const lastStep = steps[steps.length - 1].toLowerCase()

  if (lastStep.includes('sending back to coding agent') || lastStep.includes('fail: review gate')) return 2
  if (lastStep.includes('fail:') && lastStep.includes('test')) return 3

  for (let i = NODES.length - 1; i >= 0; i--) {
    if (lastStep.includes(NODES[i].match.toLowerCase())) return i
  }
  return 0
}

// Per-node status: 'idle' | 'running' | 'done'
export function getNodeStatuses(steps, loading) {
  const activeIndex = getActiveIndex(steps)
  return NODES.map((node, i) => {
    let status = 'idle'
    if (i < activeIndex) status = 'done'
    else if (i === activeIndex) status = loading ? 'running' : 'done'
    return { ...node, status }
  })
}

// Find the most recent log line that matched a given node, for a short live caption
export function lastLineForNode(steps, node) {
  for (let i = steps.length - 1; i >= 0; i--) {
    if (steps[i].toLowerCase().includes(node.match.toLowerCase())) return steps[i]
  }
  return null
}

export function isLooping(steps) {
  if (!steps.length) return false
  const last = steps[steps.length - 1].toLowerCase()
  return last.includes('sending back to coding agent') || last.includes('fail: review gate')
}
