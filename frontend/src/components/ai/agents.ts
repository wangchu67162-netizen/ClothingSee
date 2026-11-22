/** 五个智能体的固定身份信息（与 docs/CONTRACTS.md 一致，只做前端展示映射）。 */

export interface AgentMeta {
  id: string
  name: string
  role: string
  color: string
  short: string
}

export const AGENT_ORDER = ['fashion', 'art', 'aesthetics', 'price', 'comfort'] as const

export const AGENT_META: Record<string, AgentMeta> = {
  fashion: {
    id: 'fashion',
    name: '时尚智能体',
    role: '趋势 · 廓形 · 场合',
    color: '#D8BE93',
    short: '尚',
  },
  art: {
    id: 'art',
    name: '艺术智能体',
    role: '色彩 · 肌理 · 视觉语言',
    color: '#FF6B3D',
    short: '艺',
  },
  aesthetics: {
    id: 'aesthetics',
    name: '审美智能体',
    role: '比例 · 气质 · 整体造型',
    color: '#6E8B86',
    short: '美',
  },
  price: {
    id: 'price',
    name: '价格智能体',
    role: '预算 · 性价比 · 替代款',
    color: '#9B8BB4',
    short: '价',
  },
  comfort: {
    id: 'comfort',
    name: '舒适度智能体',
    role: '面料 · 体感 · 护理',
    color: '#C4A484',
    short: '适',
  },
  moderator: {
    id: 'moderator',
    name: '主持人',
    role: '广播 · 汇总 · 节奏',
    color: '#F5EFE6',
    short: '主',
  },
}

export function agentMeta(agentId?: string, fallbackName?: string): AgentMeta {
  if (agentId && AGENT_META[agentId]) return AGENT_META[agentId]
  const name = fallbackName || agentId || '智能体'
  return {
    id: agentId || 'unknown',
    name,
    role: '圆桌成员',
    color: '#B9B0A2',
    short: name.slice(0, 1),
  }
}
