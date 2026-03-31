import { useState, useEffect } from 'react'

const API = 'http://localhost:8000'

const STATUS_LABEL = { active: '稼働中', busy: '処理中', idle: '待機中' }
const STATUS_COLOR = { active: '#22C55E', busy: '#F59E0B', idle: '#94A3B8' }
const PRIORITY_LABEL = { high: '高', medium: '中', low: '低' }
const PRIORITY_COLOR = { high: '#EF4444', medium: '#F59E0B', low: '#22C55E' }
const TASK_STATUS_LABEL = { pending: '未着手', in_progress: '処理中', done: '完了' }

function StatCard({ label, value, sub, color }) {
  return (
    <div style={{
      background: '#fff', borderRadius: 12, padding: '20px 24px',
      boxShadow: '0 1px 4px rgba(0,0,0,0.08)', borderTop: `4px solid ${color}`,
      minWidth: 160, flex: 1
    }}>
      <div style={{ fontSize: 13, color: '#64748B', marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 32, fontWeight: 700, color }}>{value}</div>
      {sub && <div style={{ fontSize: 12, color: '#94A3B8', marginTop: 4 }}>{sub}</div>}
    </div>
  )
}

function AgentCard({ agent, selected, onClick }) {
  return (
    <div onClick={onClick} style={{
      background: selected ? agent.color : '#fff',
      color: selected ? '#fff' : '#1A202C',
      borderRadius: 12, padding: '16px 18px', cursor: 'pointer',
      boxShadow: selected ? `0 4px 14px ${agent.color}55` : '0 1px 4px rgba(0,0,0,0.08)',
      border: `2px solid ${selected ? agent.color : '#E2E8F0'}`,
      transition: 'all 0.15s ease',
      display: 'flex', flexDirection: 'column', gap: 8
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontWeight: 700, fontSize: 14 }}>{agent.name}</span>
        <span style={{
          fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 20,
          background: selected ? 'rgba(255,255,255,0.25)' : STATUS_COLOR[agent.status] + '22',
          color: selected ? '#fff' : STATUS_COLOR[agent.status]
        }}>
          ● {STATUS_LABEL[agent.status]}
        </span>
      </div>
      <div style={{ fontSize: 12, opacity: selected ? 0.85 : 0.6 }}>{agent.role}</div>
      <div style={{ display: 'flex', gap: 12, fontSize: 12, marginTop: 4 }}>
        <span>完了 <strong>{agent.tasks_completed}</strong></span>
        <span>未処理 <strong style={{ color: selected ? '#FCD34D' : '#EF4444' }}>{agent.tasks_pending}</strong></span>
      </div>
    </div>
  )
}

function TaskRow({ task }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12,
      padding: '12px 16px', borderBottom: '1px solid #F1F5F9',
      fontSize: 13
    }}>
      <span style={{
        width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
        background: PRIORITY_COLOR[task.priority]
      }} />
      <span style={{ flex: 1, fontWeight: 500 }}>{task.title}</span>
      <span style={{
        fontSize: 11, padding: '2px 8px', borderRadius: 20, flexShrink: 0,
        background: PRIORITY_COLOR[task.priority] + '18',
        color: PRIORITY_COLOR[task.priority], fontWeight: 600
      }}>
        優先度{PRIORITY_LABEL[task.priority]}
      </span>
      <span style={{ color: '#64748B', flexShrink: 0, minWidth: 80 }}>{task.agent_name}</span>
      <span style={{
        fontSize: 11, padding: '2px 8px', borderRadius: 20, flexShrink: 0,
        background: task.status === 'in_progress' ? '#F59E0B18' : '#94A3B818',
        color: task.status === 'in_progress' ? '#F59E0B' : '#94A3B8', fontWeight: 600
      }}>
        {TASK_STATUS_LABEL[task.status]}
      </span>
      {task.deadline && (
        <span style={{ color: '#94A3B8', fontSize: 12, flexShrink: 0 }}>
          期限 {task.deadline}
        </span>
      )}
    </div>
  )
}

export default function App() {
  const [agents, setAgents] = useState([])
  const [tasks, setTasks] = useState([])
  const [stats, setStats] = useState(null)
  const [selectedAgent, setSelectedAgent] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [activeTab, setActiveTab] = useState('dashboard')

  useEffect(() => {
    Promise.all([
      fetch(`${API}/api/agents`).then(r => r.json()),
      fetch(`${API}/api/tasks`).then(r => r.json()),
      fetch(`${API}/api/stats`).then(r => r.json()),
    ]).then(([a, t, s]) => {
      setAgents(a)
      setTasks(t)
      setStats(s)
      setLoading(false)
    }).catch(() => {
      setError('バックエンドAPIに接続できません。サーバーを起動してください（port 8000）')
      setLoading(false)
    })
  }, [])

  const filteredTasks = selectedAgent
    ? tasks.filter(t => t.agent_id === selectedAgent)
    : tasks

  const nav = (label, key) => (
    <button onClick={() => setActiveTab(key)} style={{
      background: activeTab === key ? '#1F4E79' : 'transparent',
      color: activeTab === key ? '#fff' : '#94A3B8',
      border: 'none', borderRadius: 8, padding: '8px 16px',
      cursor: 'pointer', fontWeight: activeTab === key ? 700 : 400,
      fontSize: 14, transition: 'all 0.15s'
    }}>{label}</button>
  )

  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      {/* サイドバー */}
      <aside style={{
        width: 220, background: '#0F2744', color: '#fff',
        display: 'flex', flexDirection: 'column', flexShrink: 0
      }}>
        <div style={{ padding: '28px 20px 16px' }}>
          <div style={{ fontSize: 11, color: '#60A5FA', fontWeight: 700, letterSpacing: 1, marginBottom: 6 }}>
            税理士事務所
          </div>
          <div style={{ fontSize: 17, fontWeight: 700, lineHeight: 1.3 }}>
            AI エージェント<br />管理ダッシュボード
          </div>
        </div>
        <hr style={{ border: 'none', borderTop: '1px solid #1E3A5F', margin: '0 16px 16px' }} />
        <nav style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '0 12px' }}>
          {nav('ダッシュボード', 'dashboard')}
          {nav('エージェント一覧', 'agents')}
          {nav('タスク一覧', 'tasks')}
        </nav>
        <div style={{ flex: 1 }} />
        <div style={{ padding: '16px 20px', fontSize: 11, color: '#475569' }}>
          v0.1.0 — {new Date().toLocaleDateString('ja-JP')}
        </div>
      </aside>

      {/* メインエリア */}
      <main style={{ flex: 1, padding: '32px', overflowY: 'auto' }}>
        {loading && <div style={{ color: '#64748B', fontSize: 16 }}>読み込み中...</div>}
        {error && (
          <div style={{
            background: '#FEF2F2', border: '1px solid #FECACA', color: '#DC2626',
            borderRadius: 10, padding: '16px 20px', marginBottom: 24
          }}>
            ⚠️ {error}
          </div>
        )}

        {/* ダッシュボード */}
        {activeTab === 'dashboard' && !loading && (
          <>
            <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 24, color: '#1F4E79' }}>
              ダッシュボード
            </h1>
            {stats && (
              <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 32 }}>
                <StatCard label="総エージェント数" value={stats.total_agents} color="#1F4E79" />
                <StatCard label="稼働中" value={stats.active_agents} sub="アクティブ" color="#22C55E" />
                <StatCard label="処理中" value={stats.busy_agents} sub="ビジー" color="#F59E0B" />
                <StatCard label="完了タスク総数" value={stats.tasks_completed_total} color="#2E75B6" />
                <StatCard label="未処理タスク" value={stats.tasks_pending_total} sub="要対応" color="#EF4444" />
              </div>
            )}

            <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 16, color: '#334155' }}>
              直近のタスク
            </h2>
            <div style={{ background: '#fff', borderRadius: 12, boxShadow: '0 1px 4px rgba(0,0,0,0.08)', overflow: 'hidden' }}>
              {tasks.filter(t => t.status !== 'done').slice(0, 6).map(t => (
                <TaskRow key={t.id} task={t} />
              ))}
            </div>
          </>
        )}

        {/* エージェント一覧 */}
        {activeTab === 'agents' && !loading && (
          <>
            <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 8, color: '#1F4E79' }}>
              エージェント一覧
            </h1>
            <p style={{ color: '#64748B', fontSize: 13, marginBottom: 24 }}>
              エージェントをクリックすると担当タスクを絞り込めます
            </p>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 14, marginBottom: 32 }}>
              {agents.map(a => (
                <AgentCard key={a.id} agent={a}
                  selected={selectedAgent === a.id}
                  onClick={() => setSelectedAgent(selectedAgent === a.id ? null : a.id)}
                />
              ))}
            </div>

            {selectedAgent && (
              <>
                <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 16, color: '#334155' }}>
                  {agents.find(a => a.id === selectedAgent)?.name} の担当タスク
                </h2>
                <div style={{ background: '#fff', borderRadius: 12, boxShadow: '0 1px 4px rgba(0,0,0,0.08)', overflow: 'hidden' }}>
                  {filteredTasks.length === 0
                    ? <div style={{ padding: 24, color: '#94A3B8', textAlign: 'center' }}>タスクなし</div>
                    : filteredTasks.map(t => <TaskRow key={t.id} task={t} />)
                  }
                </div>
              </>
            )}
          </>
        )}

        {/* タスク一覧 */}
        {activeTab === 'tasks' && !loading && (
          <>
            <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 24, color: '#1F4E79' }}>
              タスク一覧
            </h1>
            <div style={{ background: '#fff', borderRadius: 12, boxShadow: '0 1px 4px rgba(0,0,0,0.08)', overflow: 'hidden' }}>
              <div style={{ padding: '12px 16px', background: '#F8FAFC', borderBottom: '1px solid #E2E8F0', display: 'flex', gap: 8, fontSize: 12, color: '#64748B', fontWeight: 600 }}>
                <span style={{ width: 18 }} />
                <span style={{ flex: 1 }}>タスク名</span>
                <span style={{ width: 72 }}>優先度</span>
                <span style={{ width: 100 }}>担当AI</span>
                <span style={{ width: 72 }}>状態</span>
                <span style={{ width: 110 }}>期限</span>
              </div>
              {tasks.map(t => <TaskRow key={t.id} task={t} />)}
            </div>
          </>
        )}
      </main>
    </div>
  )
}
