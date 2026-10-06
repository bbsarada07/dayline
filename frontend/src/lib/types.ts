/** Shapes returned by the API. Kept in sync with the backend by hand. */

export type Role = "student" | "canteen" | "print" | "admin";

export type Me =
  | {
      kind: "student";
      role: "student";
      id: number;
      name: string;
      roll_no: string;
      branch: string;
      year: number;
      section: string;
      card_linked: boolean;
      card_uid: string | null; // the ID card barcode value

    }
  | { kind: "staff"; role: Exclude<Role, "student">; id: number; name: string; username: string };

export type ClockInfo = { now: string; demo: boolean; demo_mode: boolean };

export type DayItem = {
  id: string;
  kind: "class" | "break" | "free";
  start: string;
  end: string;
  status: "past" | "current" | "upcoming";
  label: string;
  subject_id: number | null;
  subject_code: string | null;
  subject_name: string | null;
  subject_kind: "theory" | "lab" | null;
  room_code: string | null;
  room_name: string | null;
};

export type TodayData = {
  date: string;
  now: string;
  items: DayItem[];
  current: DayItem | null;
  next_class: DayItem | null;
  print_jobs: PrintJob[];
  orders: Order[];
};

export type Standing = {
  held: number;
  attended: number;
  percentage: number | null;
  threshold: number;
  status: "ok" | "below" | "no_classes";
  can_miss: number;
  must_attend: number | null;
  statement: string;
};

export type SubjectAttendance = {
  subject_id: number;
  code: string;
  name: string;
  short_name: string | null;
  kind: "theory" | "lab";
  standing: Standing;
};

export type AttendanceData = { threshold: number; subjects: SubjectAttendance[] };

export type WhatIfResult = {
  subject_id: number;
  subject_name: string;
  miss: number;
  current: Standing;
  after: Standing;
};

export type DemoAccounts = {
  enabled: boolean;
  pin: string | null;
  students: { roll_no: string; name: string }[];
  staff: { username: string; name: string; role: Exclude<Role, "student"> }[];
};

export type PrintStatus = "queued" | "printing" | "ready" | "collected" | "cancelled" | "expired";

export type PrintJob = {
  id: number;
  code: string;
  original_filename: string;
  pages: number;
  copies: number;
  color: boolean;
  double_sided: boolean;
  cost: number; // paise
  deadline: string;
  est_ready_at: string;
  status: PrintStatus;
  payment_status: "unpaid" | "paid_demo";
  created_at: string;
  ready_at: string | null;
  collected_at: string | null;
  has_file: boolean;
  student_name?: string;
  roll_no?: string;
};

export type PrintUpload = { upload_id: string; original_filename: string; pages: number };

export type PrintQuote = {
  upload_id: string;
  original_filename: string;
  pages: number;
  copies: number;
  color: boolean;
  double_sided: boolean;
  rate: number;
  cost: number;
  deadline: string;
  deadline_is_default: boolean;
  deadline_reason: string | null;
  est_ready_at: string;
  jobs_ahead: number;
  warning: string | null;
};

export type PrintQueue = { to_print: PrintJob[]; ready: PrintJob[]; urgent_minutes: number };

export type AdminSettings = {
  print_rates: { bw_single: number; bw_double: number; colour_single: number; colour_double: number };
  print_rates_confirmed: boolean;
  print_seconds_per_page: number;
  [key: string]: unknown;
};

export type MenuItem = {
  id: number;
  name: string;
  price: number; // paise
  category: string;
  is_veg: boolean;
  prep_minutes: number;
  stock_today: number;
  is_available: boolean;
  can_order: boolean;
};

export type MenuData = { categories: string[]; items: MenuItem[] };

export type OrderStatus = "placed" | "preparing" | "ready" | "collected" | "cancelled" | "no_show";

export type OrderLine = { menu_item_id: number; name: string; qty: number; unit_price: number; is_veg: boolean };

export type Order = {
  id: number;
  token_no: number;
  status: OrderStatus;
  pickup_time: string;
  total: number;
  payment_status: "unpaid" | "paid_demo";
  created_at: string;
  ready_at: string | null;
  collected_at: string | null;
  items: OrderLine[];
  student_name?: string;
  roll_no?: string;
};

export type CanteenQuote = {
  lines: { menu_item_id: number; name: string; qty: number; unit_price: number; line_total: number; is_veg: boolean }[];
  total: number;
  max_prep_minutes: number;
  pickup_time: string;
  pickup_is_default: boolean;
  pickup_reason: string | null;
  earliest_pickup: string;
  pickup_slots: string[];
};

export type KitchenBoard = { placed: Order[]; preparing: Order[]; ready: Order[] };

export type PrepList = {
  window_minutes: number;
  windows: { start: string; end: string; items: { name: string; qty: number }[]; total: number }[];
};

export type SuggestedPrep = { label: string; items: (MenuItem & { suggested: number; preordered_today: number })[] };

export type CollectStatus = "collected" | "not_ready" | "nothing_to_collect" | "unknown_card" | "ignored";

export type CollectResult = {
  id: string;
  status: CollectStatus;
  station: "canteen" | "print";
  reader_id: string;
  name: string | null;
  roll_no: string | null;
  summary: string | null;
  lines: string[];
  at: string;
};

export type CollectCandidates = {
  demo_mode: boolean;
  students: { id: number; name: string; roll_no: string; has_card: boolean; ready: number; waiting: number }[];
};
