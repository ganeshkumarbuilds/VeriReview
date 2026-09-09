import { NODES, getActiveIndex } from '../utils/agentPipeline'

const roleAccent = {
  plan: { active: 'bg-indigo-500 border-indigo-500 text-white', label: 'text-indigo-300' },
  build: { active: 'bg-indigo-500 border-indigo-500 text-white', label: 'text-indigo-300' },
  review: { active: 'bg-amber-400 border-amber-400 text-slate-950', label: 'text-amber-300' },
  verify: { active: 'bg-emerald-400 border-emerald-400 text-slate-950', label: 'text-emerald-300' },
}

export default function PipelineDiagram({ steps, isLooping }) {
  const activeIndex = getActiveIndex(steps)

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-6">
      <div className="flex items-center justify-between relative">
        {NODES.map((node, i) => {
          const isDone = i < activeIndex
          const isActive = i === activeIndex
          const accent = roleAccent[node.role]
          return (
            <div key={node.key} className="flex flex-col items-center flex-1 relative z-10">
              <div
                className={`w-10 h-10 rounded-full flex items-center justify-center text-xs font-bold border-2 transition-all
                  ${isActive ? accent.active + ' animate-pulse scale-110' : ''}
                  ${isDone ? 'bg-emerald-500/15 border-emerald-500 text-emerald-400' : ''}
                  ${!isActive && !isDone ? 'bg-slate-800 border-slate-700 text-slate-500' : ''}
                `}
              >
                {isDone ? '✓' : i + 1}
              </div>
              <span
                className={`text-xs mt-2 text-center ${
                  isActive ? accent.label + ' font-semibold' : 'text-slate-500'
                }`}
              >
                {node.label}
              </span>
              {(node.role === 'review' || node.role === 'verify') && (
                <span
                  className={`mt-1 text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded ${
                    node.role === 'review'
                      ? 'text-amber-400/70 bg-amber-400/10'
                      : 'text-emerald-400/70 bg-emerald-400/10'
                  }`}
                >
                  {node.role === 'review' ? 'trust' : 'verified'}
                </span>
              )}
            </div>
          )
        })}
        <div
          className="absolute top-5 left-0 right-0 h-0.5 bg-slate-800 -z-0"
          style={{ marginLeft: '5%', marginRight: '5%' }}
        />
      </div>

      {isLooping && (
        <div className="mt-4 text-center text-xs text-orange-400 animate-pulse">
          ↩ FAIL — Coding Agent fixing, then TEST → VERIFY → REVIEW
        </div>
      )}
    </div>
  )
}