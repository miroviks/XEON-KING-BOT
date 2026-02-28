
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
  tg_id INTEGER PRIMARY KEY,
  username TEXT,
  full_name TEXT,
  display_name TEXT,
  is_admin INTEGER DEFAULT 0,
  is_member INTEGER DEFAULT 0,
  is_investor INTEGER DEFAULT 0,
  is_active INTEGER DEFAULT 1,
  mute_regular INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS accounts (
  account_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  balance REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS loans (
  loan_id INTEGER PRIMARY KEY AUTOINCREMENT,
  investor_id TEXT NOT NULL,
  principal REAL NOT NULL,
  interest_percent REAL NOT NULL DEFAULT 0,
  due_date TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open', -- open/paid/cancelled
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS deals (
  deal_id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  closed_at TEXT,
  status TEXT NOT NULL DEFAULT 'bought',  -- bought/in_stock/testing/listing/listed/shipping/sold/return
  deal_type TEXT NOT NULL,               -- resale/repair/pc_build_project/service_build/service_diagnostic
  funding_source TEXT NOT NULL,          -- capital/investor/loan
  investor_id TEXT,
  loan_id INTEGER,
  list_price REAL NOT NULL DEFAULT 0,
  buy_price REAL NOT NULL DEFAULT 0,
  bargain_amount REAL NOT NULL DEFAULT 0,
  notes TEXT,
  last_listing_update TEXT,
  FOREIGN KEY(loan_id) REFERENCES loans(loan_id)
);

CREATE TABLE IF NOT EXISTS deal_items (
  item_id INTEGER PRIMARY KEY AUTOINCREMENT,
  deal_id INTEGER NOT NULL,
  category TEXT NOT NULL DEFAULT 'Электроника',
  subcategory TEXT NOT NULL,
  title TEXT NOT NULL,
  estimate_before REAL,
  forecast_after REAL,
  sell_price REAL,
  sell_date TEXT,
  delivery_type TEXT,
  fee_percent REAL,
  buy_alloc REAL,
  expense_alloc REAL,
  location_holder TEXT,
  FOREIGN KEY(deal_id) REFERENCES deals(deal_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS expenses (
  expense_id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  amount REAL NOT NULL,
  exp_type TEXT NOT NULL,
  description TEXT,
  deal_id INTEGER,
  created_by INTEGER,
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(deal_id) REFERENCES deals(deal_id) ON DELETE SET NULL,
  FOREIGN KEY(created_by) REFERENCES users(tg_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS deal_tasks (
  task_id INTEGER PRIMARY KEY AUTOINCREMENT,
  deal_id INTEGER NOT NULL,
  task_type TEXT NOT NULL,
  complexity TEXT,
  ai_mult REAL DEFAULT 1,
  comment TEXT,
  done_date TEXT NOT NULL,
  created_by INTEGER,
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(deal_id) REFERENCES deals(deal_id) ON DELETE CASCADE,
  FOREIGN KEY(created_by) REFERENCES users(tg_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS deal_task_performers (
  task_id INTEGER NOT NULL,
  performer_id INTEGER NOT NULL,
  PRIMARY KEY (task_id, performer_id),
  FOREIGN KEY(task_id) REFERENCES deal_tasks(task_id) ON DELETE CASCADE,
  FOREIGN KEY(performer_id) REFERENCES users(tg_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS attachments (
  attachment_id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER,
  deal_id INTEGER,
  kind TEXT NOT NULL,
  file_path TEXT NOT NULL,
  uploaded_by INTEGER,
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(task_id) REFERENCES deal_tasks(task_id) ON DELETE SET NULL,
  FOREIGN KEY(deal_id) REFERENCES deals(deal_id) ON DELETE SET NULL,
  FOREIGN KEY(uploaded_by) REFERENCES users(tg_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS general_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  creator_id INTEGER,
  assignee_id INTEGER,
  priority TEXT NOT NULL DEFAULT 'mid',
  title TEXT NOT NULL,
  description TEXT,
  due_date TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(creator_id) REFERENCES users(tg_id),
  FOREIGN KEY(assignee_id) REFERENCES users(tg_id)
);

CREATE TABLE IF NOT EXISTS transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  account_from TEXT,
  account_to TEXT,
  amount REAL NOT NULL,
  reason TEXT,
  deal_id INTEGER,
  created_by INTEGER,
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(deal_id) REFERENCES deals(deal_id) ON DELETE SET NULL,
  FOREIGN KEY(created_by) REFERENCES users(tg_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS payouts (
  payout_id INTEGER PRIMARY KEY AUTOINCREMENT,
  deal_id INTEGER NOT NULL,
  user_id INTEGER,
  investor_id TEXT,
  amount REAL NOT NULL,
  kind TEXT NOT NULL,      -- performer/investor/bargain
  is_paid INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now')),
  paid_at TEXT,
  FOREIGN KEY(deal_id) REFERENCES deals(deal_id) ON DELETE CASCADE,
  FOREIGN KEY(user_id) REFERENCES users(tg_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS deal_close_summary (
  deal_id INTEGER PRIMARY KEY,
  profit REAL NOT NULL,
  cap_rate REAL NOT NULL,
  cap_cut REAL NOT NULL,
  inv_cut REAL NOT NULL,
  performer_pool REAL NOT NULL,
  bargain_bonus REAL NOT NULL,
  payouts_total REAL NOT NULL,
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(deal_id) REFERENCES deals(deal_id) ON DELETE CASCADE
);
