/** Shared frontend types. Mirrors backend/app/schemas.py — append-only. */

export interface User {
  id: number
  username: string
  nickname: string
  created_at?: string | null
}

export interface AuthResponse {
  access_token: string
  token_type: string
  user: User
}

export type ProductCategory = '外套' | '上装' | '连衣裙' | '下装' | '配饰'

export interface Product {
  id: number
  sku: string
  name: string
  subtitle: string
  category: ProductCategory | string
  price: number
  original_price?: number | null
  description: string
  fabric: string
  fit: string
  style_tags: string[]
  colors: string[]
  sizes: string[]
  image: string
  gallery: string[]
  stock: number
  rating: number
  sales: number
  occasion?: string
  season?: string
  comfort?: Record<string, string | number>
  featured?: boolean
  similarity?: number | null
}

export interface ProductList {
  items: Product[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface Category {
  name: string
  count: number
}

export interface ImageSearchResult {
  items: Product[]
  distance_metric: string
  backend: string
  vision?: Record<string, unknown> | null
}

export interface CartItem {
  id: number
  product: Product
  quantity: number
  size: string
  color: string
  line_total: number
}

export interface Cart {
  items: CartItem[]
  total_quantity: number
  total_amount: number
}

export interface ShippingInfo {
  name: string
  phone: string
  address: string
}

export interface OrderItem {
  id: number
  product_id?: number | null
  name: string
  image: string
  price: number
  quantity: number
  size: string
  color: string
}

export interface Order {
  id: number
  order_no: string
  status: string
  source: string
  total: number
  shipping_name: string
  shipping_phone: string
  shipping_address: string
  note: string
  external_ref?: string | null
  agent_session_id?: string | null
  created_at: string
  items: OrderItem[]
}

export interface Meta {
  app_name: string
  version: string
  mode: 'qwen' | 'mock'
  llm_mode: string
  small_model_mode: string
  demo_username: string
  demo_password: string
  features: Record<string, boolean>
}

/* ------------------------------------------------------------------ small models */

export interface VisionEmbed {
  embedding: number[]
  dim: number
  model_version: string
  backend: string
}

export interface SimilarMatch {
  product: Product
  distance: number
  similarity: number
}

export interface VisionSimilar {
  query_embedding: number[]
  matches: SimilarMatch[]
  backend: string
  model_version: string
  elapsed_ms: number
}

export interface KgNode {
  id: string
  label: string
  type: string
  meta?: Record<string, unknown>
}

export interface KgEdge {
  source: string
  target: string
  relation: string
  weight: number
  meta?: Record<string, unknown>
}

export interface KgGraph {
  nodes: KgNode[]
  edges: KgEdge[]
  metric?: string
  meta?: Record<string, unknown>
}

/* ------------------------------------------------------------------ agents */

export type AgentId = 'fashion' | 'art' | 'aesthetics' | 'price' | 'comfort'

export interface VisionAnalysis {
  category: string
  colors: string[]
  style: string[]
  material: string[]
  occasion: string
  body_hints: string
  summary: string
  confidence: number
}

export interface AgentScore {
  product_id: number
  score: number
  reason: string
}

export interface AgentMessage {
  id?: number
  session_id?: string
  seq?: number
  round: number
  agent: AgentId | string
  agent_name?: string
  role?: string
  message_type?: string
  recipients?: string[]
  content: string
  scores?: AgentScore[]
  payload?: Record<string, unknown> | null
  created_at?: string
}

export interface RecommendationProduct {
  product: Product
  score: number
  reasons: string[]
  agent_scores: Record<string, number>
}

export interface RecommendationFinal {
  session_id: string
  mode: 'mock' | 'qwen'
  vision: VisionAnalysis
  candidates: Product[]
  recommendations: RecommendationProduct[]
  outfit: Product[]
  outfit_total: number
  advice: string
  kg: KgGraph | Record<string, unknown>
  elapsed_ms: number
}

export interface AgentSession {
  id: string
  kind: 'stylist' | 'assistant'
  status: 'running' | 'done' | 'failed'
  mode?: string
  error?: string | null
  result?: Record<string, unknown> | null
  created_at: string
  updated_at?: string | null
}

export interface SseEnvelope<T = unknown> {
  event: string
  data: T
  id?: string
}

/* ------------------------------------------------------------------ assistant */

export interface BrowseStep {
  index: number
  action: string
  status: 'running' | 'done' | 'failed'
  detail?: string
  screenshot?: string | null
}

export interface AssistantProductCard {
  product: Product
  platform_url: string
  mall_url?: string
}

export interface AssistantIntent {
  intent: 'recommend' | 'order' | 'chat' | 'unknown'
  query: string
  size?: string
  color?: string
  confidence?: number
}

export interface AssistantTurn {
  role: 'user' | 'assistant'
  content: string
  intent?: AssistantIntent
  products?: AssistantProductCard[]
  steps?: BrowseStep[]
  orderNo?: string
  status?: 'streaming' | 'done' | 'error'
}

/* ------------------------------------------------------------------ env */

export interface ApiErrorShape {
  detail?: string | { msg?: string }[]
}
