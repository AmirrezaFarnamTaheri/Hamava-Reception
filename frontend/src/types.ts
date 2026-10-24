export interface User {
  id: string;
  email: string;
  name: string;
  role: string;
  tenant_id: string;
  tenant_name: string;
  permissions?: string[];
}
export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User;
}
export interface Clinic {
  id: string;
  name: string;
  slug: string;
  role: string;
  timezone: string;
  settings_version: number;
  building_id?: string | null;
}
export interface Practitioner {
  id: string;
  name: string;
  specialty: string;
  active: boolean;
  working_hours?: Record<string, string[][]> | null;
}
export interface Service {
  id: string;
  name: string;
  provider_ids: string[];
  duration_minutes: number;
  buffer_minutes: number;
  price_toman: number;
  deposit_toman: number;
  requires_approval: boolean;
  description: string;
  resource_ids?: string[];
  active?: boolean;
}
export interface Slot {
  slot_id: string;
  provider_id: string;
  service_id: string;
  start_at: string;
  end_at: string;
  local_date: string;
  local_time: string;
  display: string;
  timezone: string;
  available: boolean;
  settings_version: number;
}
export interface Appointment {
  id: string;
  reference: string;
  provider_id: string;
  provider_name: string;
  service_id: string;
  service_name: string;
  patient_name: string;
  phone_masked: string;
  start_at: string;
  end_at: string;
  local_date: string;
  local_time: string;
  jalali_display: string;
  status: string;
  attendance: string | null;
  price_toman: number;
  deposit_toman: number;
  payment_status: string;
  notification_status: string;
  version: number | string;
  authority?: "internal" | "external";
  created_at: string | null;
  reminder_opt_in: boolean | null;
  last_known_status?: string | null;
  verified_at?: string | null;
  operation_id?: string | null;
  disruptions?: { id: string; state: string }[];
  payment_terms?: PaymentTerms | null;
  payment_expires_at?: string | null;
}
export interface PaymentTerms {
  version: number;
  enabled: boolean;
  synthetic?: boolean;
  hold_minutes: number;
  deposit_terms: string;
  cancellation_terms: string;
  refund_terms: string;
}
export interface StaffTask {
  id: string;
  reason: string;
  summary: string;
  priority: string;
  status: string;
  call_id: string | null;
  appointment_id: string | null;
  created_at: string;
  resolved_at: string | null;
  resolution: string | null;
}
export interface Notice {
  id: string;
  appointment_id: string;
  purpose: string;
  recipient_masked: string;
  status: string;
  attempts: number;
  provider_id: string | null;
  created_at: string;
  updated_at: string;
  last_error_code: string | null;
}
export interface AuditEvent {
  id: string;
  action: string;
  entity_type: string;
  entity_id: string;
  actor_id: string;
  details: Record<string, unknown>;
  created_at: string;
}
export interface Dashboard {
  clinic: {
    id: string;
    name: string;
    timezone: string;
    mode: string;
    settings_version: number;
  };
  date: string;
  metrics: {
    appointments_today: number;
    confirmed_today: number;
    pending_tasks: number;
    active_calls: number;
    notifications_failed: number;
    minutes_used: number;
  };
  appointments: Appointment[];
  tasks: StaffTask[];
  notifications: Notice[];
  recent_activity: AuditEvent[];
}
export interface Faq {
  question: string;
  answer: string;
  category: string;
  approved_by?: string;
  effective_at?: string | null;
  expires_at?: string | null;
  source?: string;
  keywords?: string[];
}
export interface Settings {
  id: string;
  name: string;
  slug: string;
  timezone: string;
  mode: string;
  settings_version: number;
  address: string;
  phone: string;
  website: string;
  working_hours: Record<string, string[][]>;
  holidays: string[];
  faq: Faq[];
  retention_days: number;
  lead_time_minutes: number;
  booking_horizon_days: number;
  cancellation_notice_hours: number;
  quiet_hours: { start: string; end: string } | string[];
  monthly_minute_budget: number;
}
export interface Usage {
  period: string;
  minutes: number;
  calls: number;
  bookings: number;
  events: {
    id: string;
    kind: string;
    quantity: number;
    unit: string;
    cost_toman: number;
    created_at: string;
  }[];
}
export interface Capabilities {
  audio_input?: boolean;
  audio_output?: boolean;
  livekit?: boolean;
  mode?: string;
  configured?: boolean;
}
export interface PublicClinic {
  name: string;
  identity?: {
    brand_name?: string;
    brand_color?: string;
    profile_version?: number;
  };
  slug: string;
  address?: string;
  phone?: string;
  capabilities?: Capabilities;
  greeting?: string;
  notice?: string;
  processing_notice?: string | null;
  transcript_retention_days?: number;
  processing_notice_fingerprint: string;
}
export interface VoiceTurn {
  turn_id: string;
  reply: string;
  state: string;
  offers?: Slot[];
  booking?: Appointment | null;
  handoff?: { status?: string; task_id?: string } | null;
  transcript?: string;
  capabilities?: Capabilities;
  payment_terms?: PaymentTerms | null;
}
export interface VoiceSession {
  session_id: string;
  token: string;
  greeting: string;
  capabilities: Capabilities;
}
