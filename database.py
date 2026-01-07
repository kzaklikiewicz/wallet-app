# -*- coding: utf-8 -*-
"""
Database module - WERSJA ZOPTYMALIZOWANA + BUDŻET DOMOWY
- Connection pooling (5 połączeń zamiast tworzenia nowych za każdym razem)
- Indeksy złożone dla częstych zapytań
- WAL mode dla lepszej współbieżności
- Optymalizacja PRAGMA settings
- Dodane tabele dla budżetu domowego
"""

import sqlite3
from contextlib import contextmanager
import logging
from queue import Queue, Empty
from threading import Lock
import time

logger = logging.getLogger(__name__)

# OPTYMALIZACJA 1: Connection Pool
class ConnectionPool:
    """Thread-safe connection pool dla SQLite"""
    
    def __init__(self, db_name, pool_size=5):
        self.db_name = db_name
        self.pool_size = pool_size
        self.pool = Queue(maxsize=pool_size)
        self.lock = Lock()
        self._init_pool()
        logger.info(f"Connection pool zainicjalizowany: {pool_size} połączeń")
    
    def _init_pool(self):
        """Inicjalizuje pool połączeń"""
        for _ in range(self.pool_size):
            conn = self._create_connection()
            self.pool.put(conn)
    
    def _create_connection(self):
        """Tworzy nowe połączenie z optymalnymi ustawieniami"""
        conn = sqlite3.connect(self.db_name, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        
        # OPTYMALIZACJA: WAL mode - lepsza współbieżność
        conn.execute('PRAGMA journal_mode=WAL')
        # OPTYMALIZACJA: Zwiększ cache
        conn.execute('PRAGMA cache_size=-64000')  # 64MB
        # OPTYMALIZACJA: Synchronizacja NORMAL (szybsza)
        conn.execute('PRAGMA synchronous=NORMAL')
        # OPTYMALIZACJA: Memory-mapped I/O
        conn.execute('PRAGMA mmap_size=268435456')  # 256MB
        
        # DODATKOWE OPTYMALIZACJE dla szybszego ładowania:
        conn.execute('PRAGMA temp_store=MEMORY')  # Temp w RAM zamiast dysku
        conn.execute('PRAGMA page_size=4096')  # Optymalny rozmiar strony
        conn.execute('PRAGMA auto_vacuum=INCREMENTAL')  # Automatyczne czyszczenie
        
        return conn
    
    @contextmanager
    def get_connection(self):
        """Context manager dla połączenia z poolem"""
        conn = None
        try:
            # Pobierz połączenie z poolem (timeout 5s)
            conn = self.pool.get(timeout=5)
            yield conn
        except Empty:
            logger.error("Timeout pobierania połączenia z poolem")
            # Fallback - stwórz tymczasowe połączenie
            conn = self._create_connection()
            yield conn
        finally:
            if conn:
                try:
                    # Zwróć połączenie do poolem
                    self.pool.put_nowait(conn)
                except:
                    # Pool pełny - zamknij połączenie
                    conn.close()
    
    def close_all(self):
        """Zamyka wszystkie połączenia w poolie"""
        while not self.pool.empty():
            try:
                conn = self.pool.get_nowait()
                conn.close()
            except Empty:
                break
        logger.info("Connection pool zamknięty")


class Database:
    def __init__(self, db_name='portfolio.db'):
        self.db_name = db_name
        # OPTYMALIZACJA: Użyj connection pooling zamiast pojedynczych połączeń
        self.pool = ConnectionPool(db_name, pool_size=5)
        self._init_db()
        logger.info(f"Database zainicjalizowana: {db_name}")
    
    def _init_db(self):
        """Inicjalizuje strukturę bazy danych z optymalizacjami"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            
            # ============================================================
            # TABELE PORTFOLIO
            # ============================================================
            
            # Tabela positions
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    buy_price REAL NOT NULL,
                    purchase_date TEXT,
                    instrument_type TEXT DEFAULT 'Akcje',
                    leverage INTEGER DEFAULT 1,
                    currency TEXT DEFAULT 'USD',
                    usd_rate REAL,
                    eur_rate REAL,
                    alert_price REAL,
                    direction TEXT DEFAULT 'Long',
                    swap_daily REAL,
                    dividend REAL DEFAULT 0
                )
            ''')
            
            # MIGRACJA: Dodaj brakujące kolumny do istniejącej tabeli
            cursor.execute("PRAGMA table_info(positions)")
            existing_columns = {row[1] for row in cursor.fetchall()}
            
            # MIGRACJA: Zmiana buy_date na purchase_date
            if 'buy_date' in existing_columns and 'purchase_date' not in existing_columns:
                try:
                    cursor.execute("ALTER TABLE positions RENAME COLUMN buy_date TO purchase_date")
                    logger.info("Zmieniono nazwę kolumny buy_date na purchase_date")
                except Exception as e:
                    logger.warning(f"Nie udało się zmienić nazwy kolumny buy_date: {e}")
            
            # Lista nowych kolumn które mogą brakować
            migrations = [
                ("alert_price", "ALTER TABLE positions ADD COLUMN alert_price REAL"),
                ("direction", "ALTER TABLE positions ADD COLUMN direction TEXT DEFAULT 'Long'"),
                ("swap_daily", "ALTER TABLE positions ADD COLUMN swap_daily REAL"),
                ("dividend", "ALTER TABLE positions ADD COLUMN dividend REAL DEFAULT 0"),
                ("purchase_date", "ALTER TABLE positions ADD COLUMN purchase_date TEXT")
            ]
            
            for col_name, sql in migrations:
                if col_name not in existing_columns:
                    try:
                        cursor.execute(sql)
                        logger.info(f"Dodano brakującą kolumnę: {col_name}")
                    except Exception as e:
                        logger.warning(f"Nie udało się dodać kolumny {col_name}: {e}")
            
            conn.commit()
            
            # Tabela closed_positions
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS closed_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    buy_price REAL NOT NULL,
                    sell_price REAL NOT NULL,
                    purchase_date TEXT,
                    close_date TEXT,
                    profit REAL,
                    instrument_type TEXT DEFAULT 'Akcje',
                    leverage INTEGER DEFAULT 1,
                    currency TEXT DEFAULT 'USD',
                    usd_rate_buy REAL,
                    eur_rate_buy REAL,
                    usd_rate_sell REAL,
                    eur_rate_sell REAL,
                    dividend REAL DEFAULT 0,
                    swap REAL DEFAULT 0
                )
            ''')
            
            # Tabela history
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    buy_price REAL NOT NULL CHECK(buy_price > 0),
                    sell_price REAL NOT NULL CHECK(sell_price > 0),
                    quantity REAL NOT NULL CHECK(quantity > 0),
                    profit REAL NOT NULL,
                    buy_date TEXT NOT NULL,
                    sell_date TEXT NOT NULL,
                    usd_rate REAL,
                    eur_rate REAL,
                    instrument_type TEXT DEFAULT 'Akcje',
                    leverage INTEGER DEFAULT 1,
                    direction TEXT DEFAULT 'Long',
                    swap_daily REAL,
                    swap_cost REAL DEFAULT 0,
                    dividend REAL DEFAULT 0
                )
            ''')
            
            # Tabela watchlist
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS watchlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'USD',
                    hp1 REAL,
                    hp2 REAL,
                    hp3 REAL,
                    hp4 REAL,
                    note TEXT,
                    hp1_triggered INTEGER DEFAULT 0,
                    hp2_triggered INTEGER DEFAULT 0,
                    hp3_triggered INTEGER DEFAULT 0,
                    hp4_triggered INTEGER DEFAULT 0,
                    UNIQUE(ticker, currency)
                )
            ''')
            
            # Tabela strategy_to_play - poziomy do rozegrania
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS strategy_to_play (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    strategy_percent INTEGER NOT NULL,
                    direction TEXT NOT NULL,
                    levels TEXT NOT NULL,
                    opened_levels TEXT DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(ticker)
                )
            ''')
            
            # Tabela strategy_playing - aktywnie rozgrywane strategie
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS strategy_playing (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    strategy_percent INTEGER NOT NULL,
                    buy_price REAL NOT NULL,
                    quantity REAL NOT NULL,
                    close_price REAL NOT NULL,
                    direction TEXT DEFAULT 'Wzrosty',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # ============================================================
            # TABELE BUDŻET DOMOWY
            # ============================================================
            
            # Tabela budżetu - przychody
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS budget_income (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    year INTEGER NOT NULL,
                    month INTEGER NOT NULL,
                    day INTEGER NOT NULL,
                    category TEXT NOT NULL,
                    amount REAL NOT NULL DEFAULT 0,
                    comment TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Tabela budżetu - wydatki
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS budget_expense (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    year INTEGER NOT NULL,
                    month INTEGER NOT NULL,
                    day INTEGER NOT NULL,
                    category TEXT NOT NULL,
                    subcategory TEXT,
                    amount REAL NOT NULL DEFAULT 0,
                    comment TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Tabela wydatków cyklicznych/stałych
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS budget_recurring_expense (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    subcategory TEXT,
                    amount REAL NOT NULL DEFAULT 0,
                    comment TEXT,
                    day_of_month INTEGER NOT NULL,
                    start_year INTEGER NOT NULL,
                    start_month INTEGER NOT NULL,
                    duration_type TEXT NOT NULL CHECK(duration_type IN ('indefinite', 'months')),
                    duration_months INTEGER,
                    active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # ============================================================
            # TABELA USTAWIEŃ APLIKACJI
            # ============================================================
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Inicjalizacja domyślnych ustawień (jeśli nie istnieją)
            cursor.execute('''
                INSERT OR IGNORE INTO app_settings (key, value) VALUES 
                ('module_media_enabled', 'true'),
                ('module_budget_enabled', 'true'),
                ('auth_enabled', 'false'),
                ('auth_lock_after_attempts', '5'),
                ('auth_lock_duration_minutes', '15'),
                ('auto_lock_enabled', 'false'),
                ('auto_lock_minutes', '30'),
                ('lock_on_windows_lock', 'true')
            ''')
            
            conn.commit()
            logger.info("Tabela ustawień aplikacji utworzona/zaktualizowana")
            
            # ============================================================
            # TABELA AUTORYZACJI
            # ============================================================
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS auth_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    password_hash TEXT NOT NULL,
                    recovery_key_hash TEXT NOT NULL,
                    failed_attempts INTEGER DEFAULT 0,
                    locked_until TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()
            logger.info("Tabela autoryzacji utworzona/zaktualizowana")
            
            # ============================================================
            # INDEKSY DLA OPTYMALIZACJI
            # ============================================================
            
            # Indeksy dla portfolio
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_positions_currency 
                ON positions(currency)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_history_currency_date 
                ON history(currency, sell_date DESC)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_watchlist_ticker 
                ON watchlist(ticker, currency)
            ''')
            
            # Indeksy dla budżetu
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_budget_income_date 
                ON budget_income(year, month, day)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_budget_expense_date 
                ON budget_expense(year, month, day)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_budget_expense_category 
                ON budget_expense(category, subcategory)
            ''')
            
            # ============================================================
            # TABELA CACHE CENOWEGO (HYBRYDOWE ŁADOWANIE)
            # ============================================================
            
            # Tabela price_cache - przechowuje ostatnie ceny akcji
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS price_cache (
                    ticker TEXT PRIMARY KEY,
                    last_price REAL NOT NULL,
                    last_update TIMESTAMP NOT NULL,
                    company_name TEXT,
                    currency TEXT DEFAULT 'USD'
                )
            ''')
            
            # Indeks dla szybkich zapytań cache
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_price_cache_update 
                ON price_cache(last_update)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_price_cache_ticker 
                ON price_cache(ticker)
            ''')
            
            # MIGRACJA: Dodaj kolumnę opened_levels do strategy_to_play jeśli nie istnieje
            cursor.execute("PRAGMA table_info(strategy_to_play)")
            strategy_columns = {row[1] for row in cursor.fetchall()}
            if 'opened_levels' not in strategy_columns:
                try:
                    cursor.execute("ALTER TABLE strategy_to_play ADD COLUMN opened_levels TEXT DEFAULT '[]'")
                    logger.info("Dodano kolumnę opened_levels do strategy_to_play")
                except Exception as e:
                    logger.warning(f"Nie udało się dodać kolumny opened_levels: {e}")
            
            # MIGRACJA: Dodaj kolumnę direction do strategy_playing jeśli nie istnieje
            cursor.execute("PRAGMA table_info(strategy_playing)")
            playing_columns = {row[1] for row in cursor.fetchall()}
            if 'direction' not in playing_columns:
                try:
                    cursor.execute("ALTER TABLE strategy_playing ADD COLUMN direction TEXT DEFAULT 'Wzrosty'")
                    logger.info("Dodano kolumnę direction do strategy_playing")
                except Exception as e:
                    logger.warning(f"Nie udało się dodać kolumny direction: {e}")
            
            # MIGRACJA: Dodaj kolumnę note do watchlist jeśli nie istnieje
            cursor.execute("PRAGMA table_info(watchlist)")
            watchlist_columns = {row[1] for row in cursor.fetchall()}
            if 'note' not in watchlist_columns:
                try:
                    cursor.execute("ALTER TABLE watchlist ADD COLUMN note TEXT")
                    logger.info("Dodano kolumnę note do watchlist")
                except Exception as e:
                    logger.warning(f"Nie udało się dodać kolumny note: {e}")
            
            conn.commit()
            logger.info("Tabele i indeksy bazy danych utworzone/zaktualizowane (+ price_cache)")
            
            # OPTYMALIZACJA: Utwórz indeksy dla super szybkiego ładowania
            self.create_performance_indexes()
            
            # Utwórz tabele dla modułu MEDIA (zawsze tworzone, ale używane tylko gdy moduł jest włączony)
            self.create_media_tables()
    
    def create_performance_indexes(self):
        """
        Tworzy indeksy dla optymalizacji wydajności - MEGA PRZYSPIESZENIE!
        Zapytania mogą być 10-100x szybsze po dodaniu indeksów
        """
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            
            logger.info("🚀 Tworzenie indeksów wydajnościowych...")
            
            try:
                # ============================================================
                # INDEKSY DLA POSITIONS (najważniejsze!)
                # ============================================================
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_positions_currency ON positions(currency)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_positions_ticker ON positions(ticker)')
                # Indeks złożony - super szybkie dla JOIN w get_positions_with_cache
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_positions_currency_ticker ON positions(currency, ticker)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_positions_purchase_date ON positions(purchase_date)')
                
                # ============================================================
                # INDEKSY DLA HISTORY
                # ============================================================
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_history_currency ON history(currency)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_history_ticker ON history(ticker)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_history_sell_date ON history(sell_date)')
                
                # ============================================================
                # INDEKSY DLA WATCHLIST
                # ============================================================
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_watchlist_currency ON watchlist(currency)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_watchlist_ticker ON watchlist(ticker)')
                
                # ============================================================
                # INDEKSY DLA PRICE_CACHE (bardzo ważne!)
                # ============================================================
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_price_cache_ticker ON price_cache(ticker)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_price_cache_update ON price_cache(last_update)')
                # Indeks złożony dla szybkiego JOIN
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_price_cache_ticker_update ON price_cache(ticker, last_update)')
                
                # ============================================================
                # INDEKSY DLA STRATEGIES
                # ============================================================
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_strategy_to_play_currency ON strategy_to_play(currency)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_strategy_playing_currency ON strategy_playing(currency)')
                
                conn.commit()
                logger.info("✅ Indeksy wydajnościowe utworzone - ładowanie będzie SUPER SZYBKIE!")
                
            except Exception as e:
                logger.warning(f"Błąd podczas tworzenia indeksów: {e}")
    
    # ============================================================
    # METODY PORTFOLIO (zachowane z oryginalnego pliku)
    # ============================================================
    
    def add_position(self, ticker, quantity, buy_price, purchase_date=None, 
                     instrument_type='Akcje', leverage=1, currency='USD',
                     usd_rate=None, eur_rate=None, alert_price=None, direction='Long',
                     swap_daily=None, dividend=0):
        """Dodaje nową pozycję"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO positions (ticker, quantity, buy_price, purchase_date, 
                                     instrument_type, leverage, currency, usd_rate, eur_rate,
                                     alert_price, direction, swap_daily, dividend)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (ticker.upper(), quantity, buy_price, purchase_date, instrument_type, 
                  leverage, currency, usd_rate, eur_rate, alert_price, direction, 
                  swap_daily, dividend))
            
            position_id = cursor.lastrowid
            conn.commit()
            logger.info(f"Dodano pozycję: {ticker} ({currency}) - ID: {position_id}")
            return position_id
    
    def update_position(self, position_id, ticker, quantity, buy_price, purchase_date,
                       instrument_type='Akcje', leverage=1, currency='USD',
                       usd_rate=None, eur_rate=None, alert_price=None, direction='Long',
                       swap_daily=None, dividend=0):
        """Aktualizuje istniejącą pozycję"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE positions 
                SET ticker = ?, quantity = ?, buy_price = ?, purchase_date = ?, 
                    instrument_type = ?, leverage = ?, currency = ?, usd_rate = ?, 
                    eur_rate = ?, alert_price = ?, direction = ?, swap_daily = ?, dividend = ?
                WHERE id = ?
            ''', (ticker.upper(), quantity, buy_price, purchase_date, instrument_type, 
                  leverage, currency, usd_rate, eur_rate, alert_price, direction, 
                  swap_daily, dividend, position_id))
            
            conn.commit()
            logger.info(f"Zaktualizowano pozycję ID: {position_id} - {ticker}")
    
    def delete_position(self, position_id):
        """Usuwa pozycję"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM positions WHERE id = ?', (position_id,))
            conn.commit()
            logger.info(f"Usunięto pozycję ID: {position_id}")
    
    def get_positions(self, currency='USD'):
        """Pobiera wszystkie pozycje dla danej waluty"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    id,
                    ticker,
                    quantity,
                    buy_price,
                    purchase_date,
                    purchase_date as buy_date,
                    instrument_type,
                    leverage,
                    currency,
                    usd_rate,
                    eur_rate,
                    alert_price,
                    direction,
                    swap_daily,
                    dividend
                FROM positions 
                WHERE currency = ? 
                ORDER BY ticker
            ''', (currency,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_position_by_id(self, position_id):
        """Pobiera pozycję po ID"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM positions WHERE id = ?', (position_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    # Metody dla watchlist
    def add_to_watchlist(self, ticker, currency='USD', hp1=None, hp2=None, hp3=None, hp4=None, note=None):
        """Dodaje spółkę do watchlisty"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('''
                    INSERT INTO watchlist (ticker, currency, hp1, hp2, hp3, hp4, note)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (ticker.upper(), currency, hp1, hp2, hp3, hp4, note))
                
                watchlist_id = cursor.lastrowid
                conn.commit()
                logger.info(f"Dodano do watchlisty: {ticker} ({currency}) - ID: {watchlist_id}")
                return watchlist_id
            except sqlite3.IntegrityError:
                logger.warning(f"Spółka {ticker} już istnieje w watchliście {currency}")
                return None
    
    def update_watchlist(self, watchlist_id, ticker, currency, hp1=None, hp2=None, hp3=None, hp4=None, note=None):
        """Aktualizuje pozycję w watchliście"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE watchlist 
                SET ticker = ?, currency = ?, hp1 = ?, hp2 = ?, hp3 = ?, hp4 = ?, note = ?
                WHERE id = ?
            ''', (ticker.upper(), currency, hp1, hp2, hp3, hp4, note, watchlist_id))
            
            conn.commit()
            logger.info(f"Zaktualizowano watchlistę ID: {watchlist_id} - {ticker}")
    
    def delete_from_watchlist(self, watchlist_id):
        """Usuwa spółkę z watchlisty"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM watchlist WHERE id = ?', (watchlist_id,))
            conn.commit()
            logger.info(f"Usunięto z watchlisty ID: {watchlist_id}")
    
    def get_watchlist(self, currency='USD'):
        """Pobiera watchlistę dla danej waluty"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM watchlist 
                WHERE currency = ? 
                ORDER BY ticker
            ''', (currency,))
            return [dict(row) for row in cursor.fetchall()]
    
    def update_watchlist_alert_status(self, watchlist_id, hp1=None, hp2=None, hp3=None, hp4=None):
        """Aktualizuje status alertów HP dla pozycji w watchliście"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            
            # Przygotuj listę aktualizacji
            updates = []
            triggered_levels = []
            
            if hp1 is True:
                updates.append("hp1_triggered = 1")
                triggered_levels.append("HP1")
            if hp2 is True:
                updates.append("hp2_triggered = 1")
                triggered_levels.append("HP2")
            if hp3 is True:
                updates.append("hp3_triggered = 1")
                triggered_levels.append("HP3")
            if hp4 is True:
                updates.append("hp4_triggered = 1")
                triggered_levels.append("HP4")
            
            if updates:
                sql = f"UPDATE watchlist SET {', '.join(updates)} WHERE id = ?"
                cursor.execute(sql, (watchlist_id,))
                conn.commit()
                logger.info(f"Zaktualizowano status alertów dla watchlist ID {watchlist_id}: {', '.join(triggered_levels)}")
    
    def mark_hp_triggered(self, ticker, currency, hp_level):
        """Oznacza poziom HP jako triggered"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            column = f'hp{hp_level}_triggered'
            cursor.execute(f'''
                UPDATE watchlist 
                SET {column} = 1
                WHERE ticker = ? AND currency = ?
            ''', (ticker, currency))
            
            conn.commit()
            logger.info(f"{ticker}: HP{hp_level} oznaczony jako triggered")
    
    def process_triggered_hp(self, ticker, currency):
        """Przetwarza triggered HP - usuwa poziom lub całą spółkę"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, hp1, hp2, hp3, hp4, 
                       hp1_triggered, hp2_triggered, hp3_triggered, hp4_triggered
                FROM watchlist 
                WHERE ticker = ? AND currency = ?
            ''', (ticker, currency))
            
            row = cursor.fetchone()
            if not row:
                logger.warning(f"Nie znaleziono {ticker} w watchliście {currency}")
                return False
            
            item = dict(row)
            item_id = item['id']
            
            if item.get('hp1_triggered'):
                if item.get('hp2'):
                    cursor.execute('''
                        UPDATE watchlist 
                        SET hp1 = NULL, hp1_triggered = 0
                        WHERE id = ?
                    ''', (item_id,))
                    conn.commit()
                    logger.info(f"{ticker}: Usunięto HP1, czekamy na HP2")
                    return False
                else:
                    cursor.execute('DELETE FROM watchlist WHERE id = ?', (item_id,))
                    conn.commit()
                    logger.info(f"{ticker}: Brak kolejnego poziomu HP, usunięto z watchlisty")
                    return True
                    
            elif item.get('hp2_triggered'):
                if item.get('hp3'):
                    cursor.execute('''
                        UPDATE watchlist 
                        SET hp2 = NULL, hp2_triggered = 0
                        WHERE id = ?
                    ''', (item_id,))
                    conn.commit()
                    logger.info(f"{ticker}: Usunięto HP2, czekamy na HP3")
                    return False
                else:
                    cursor.execute('DELETE FROM watchlist WHERE id = ?', (item_id,))
                    conn.commit()
                    logger.info(f"{ticker}: Brak kolejnego poziomu HP, usunięto z watchlisty")
                    return True
                    
            elif item.get('hp3_triggered'):
                if item.get('hp4'):
                    cursor.execute('''
                        UPDATE watchlist 
                        SET hp3 = NULL, hp3_triggered = 0
                        WHERE id = ?
                    ''', (item_id,))
                    conn.commit()
                    logger.info(f"{ticker}: Usunięto HP3, czekamy na HP4")
                    return False
                else:
                    cursor.execute('DELETE FROM watchlist WHERE id = ?', (item_id,))
                    conn.commit()
                    logger.info(f"{ticker}: Brak kolejnego poziomu HP, usunięto z watchlisty")
                    return True
                    
            elif item.get('hp4_triggered'):
                cursor.execute('DELETE FROM watchlist WHERE id = ?', (item_id,))
                conn.commit()
                logger.info(f"{ticker}: HP4 był ostatnim poziomem, usunięto z watchlisty")
                return True
            else:
                logger.info(f"{ticker}: Żaden poziom HP nie był aktywny, brak zmian")
                return False
    
    # Metody dla history
    def add_to_history(self, ticker, currency, buy_price, sell_price, quantity, profit, 
                       buy_date, sell_date=None, usd_rate=None, eur_rate=None,
                       instrument_type='Akcje', leverage=None, direction='Long',
                       swap_daily=None, swap_cost=None, dividend=None):
        """Dodaje transakcję do historii"""
        if sell_date is None:
            from datetime import datetime
            sell_date = datetime.now().strftime('%Y-%m-%d')
        
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO history (ticker, currency, buy_price, sell_price, quantity, 
                                   profit, buy_date, sell_date, usd_rate, eur_rate, 
                                   instrument_type, leverage, direction, swap_daily, 
                                   swap_cost, dividend)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (ticker.upper(), currency, buy_price, sell_price, quantity, profit, 
                  buy_date, sell_date, usd_rate, eur_rate, instrument_type, leverage, 
                  direction, swap_daily, swap_cost or 0, dividend or 0))
            
            history_id = cursor.lastrowid
            conn.commit()
            
            logger.info(f"Dodano do historii: {ticker} ({currency}) - ID: {history_id}, Zysk: {profit:.2f}")
            return history_id
    
    def update_to_history(self, history_id, ticker, currency, buy_price, sell_price, 
                         quantity, profit, buy_date, sell_date, usd_rate=None, eur_rate=None,
                         instrument_type='Akcje', leverage=None, direction='Long',
                         swap_daily=None, dividend=None):
        """Aktualizuje transakcję w historii"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE history 
                SET ticker = ?, currency = ?, buy_price = ?, sell_price = ?, 
                    quantity = ?, profit = ?, buy_date = ?, sell_date = ?, 
                    usd_rate = ?, eur_rate = ?, instrument_type = ?, leverage = ?, 
                    direction = ?, swap_daily = ?, dividend = ?
                WHERE id = ?
            ''', (ticker.upper(), currency, buy_price, sell_price, quantity, 
                  profit, buy_date, sell_date, usd_rate, eur_rate, instrument_type, 
                  leverage, direction, swap_daily, dividend or 0, history_id))
            
            conn.commit()
            logger.info(f"Zaktualizowano historię ID: {history_id} - {ticker}, Zysk: {profit:.2f}")
    
    def delete_from_history(self, history_id):
        """Usuwa transakcję z historii"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM history WHERE id = ?', (history_id,))
            conn.commit()
            logger.info(f"Usunięto z historii ID: {history_id}")
    
    def get_history(self, currency='USD'):
        """Pobiera historię transakcji dla danej waluty"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM history 
                WHERE currency = ? 
                ORDER BY sell_date DESC
            ''', (currency,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_total_profit(self, currency='USD'):
        """Oblicza łączny zysk/stratę dla danej waluty"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT SUM(profit) as total FROM history WHERE currency = ?
            ''', (currency,))
            
            result = cursor.fetchone()
            return result['total'] if result['total'] is not None else 0.0
    
    # ============================================================
    # METODY BUDŻET DOMOWY
    # ============================================================
    
    def add_budget_income(self, year, month, day, category, amount, comment=''):
        """Dodaje przychód do budżetu"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO budget_income (year, month, day, category, amount, comment)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (year, month, day, category, amount, comment))
            
            income_id = cursor.lastrowid
            conn.commit()
            logger.info(f"Dodano przychód: {category} - {amount} PLN (ID: {income_id})")
            return income_id
    
    def update_budget_income(self, income_id, year, month, day, category, amount, comment=''):
        """Aktualizuje przychód w budżecie"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE budget_income 
                SET year = ?, month = ?, day = ?, category = ?, amount = ?, 
                    comment = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (year, month, day, category, amount, comment, income_id))
            
            conn.commit()
            logger.info(f"Zaktualizowano przychód ID: {income_id}")
    
    def delete_budget_income(self, income_id):
        """Usuwa przychód z budżetu"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM budget_income WHERE id = ?', (income_id,))
            conn.commit()
            logger.info(f"Usunięto przychód ID: {income_id}")
    
    def get_budget_income(self, year, month):
        """Pobiera przychody dla danego miesiąca"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM budget_income 
                WHERE year = ? AND month = ?
                ORDER BY day, category
            ''', (year, month))
            return [dict(row) for row in cursor.fetchall()]
    
    def add_budget_expense(self, year, month, day, category, subcategory, amount, comment=''):
        """Dodaje wydatek do budżetu"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO budget_expense (year, month, day, category, subcategory, amount, comment)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (year, month, day, category, subcategory, amount, comment))
            
            expense_id = cursor.lastrowid
            conn.commit()
            logger.info(f"Dodano wydatek: {category}/{subcategory} - {amount} PLN (ID: {expense_id})")
            return expense_id
    
    def update_budget_expense(self, expense_id, year, month, day, category, subcategory, amount, comment=''):
        """Aktualizuje wydatek w budżecie"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE budget_expense 
                SET year = ?, month = ?, day = ?, category = ?, subcategory = ?, 
                    amount = ?, comment = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (year, month, day, category, subcategory, amount, comment, expense_id))
            
            conn.commit()
            logger.info(f"Zaktualizowano wydatek ID: {expense_id}")
    
    def delete_budget_expense(self, expense_id):
        """Usuwa wydatek z budżetu"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM budget_expense WHERE id = ?', (expense_id,))
            conn.commit()
            logger.info(f"Usunięto wydatek ID: {expense_id}")
    
    def get_budget_expense(self, year, month):
        """Pobiera wydatki dla danego miesiąca"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM budget_expense 
                WHERE year = ? AND month = ?
                ORDER BY day, category, subcategory
            ''', (year, month))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_budget_summary(self, year, month):
        """Oblicza podsumowanie budżetu dla danego miesiąca"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            
            # Suma przychodów
            cursor.execute('''
                SELECT SUM(amount) as total FROM budget_income 
                WHERE year = ? AND month = ?
            ''', (year, month))
            income_result = cursor.fetchone()
            total_income = income_result['total'] if income_result['total'] is not None else 0.0
            
            # Suma wydatków
            cursor.execute('''
                SELECT SUM(amount) as total FROM budget_expense 
                WHERE year = ? AND month = ?
            ''', (year, month))
            expense_result = cursor.fetchone()
            total_expense = expense_result['total'] if expense_result['total'] is not None else 0.0
            
            balance = total_income - total_expense
            
            return {
                'total_income': total_income,
                'total_expense': total_expense,
                'balance': balance
            }
    
    def get_budget_expense_by_category(self, year, month, category):
        """Pobiera wydatki dla danej kategorii"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM budget_expense 
                WHERE year = ? AND month = ? AND category = ?
                ORDER BY day, subcategory
            ''', (year, month, category))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_all_budget_income(self):
        """Pobiera wszystkie przychody (dla eksportu)"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM budget_income 
                ORDER BY year DESC, month DESC, day DESC
            ''')
            return [dict(row) for row in cursor.fetchall()]
    
    def get_all_budget_expenses(self):
        """Pobiera wszystkie wydatki (dla eksportu)"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM budget_expense 
                ORDER BY year DESC, month DESC, day DESC
            ''')
            return [dict(row) for row in cursor.fetchall()]
    
    # ============================================================
    # WYDATKI CYKLICZNE/STAŁE
    # ============================================================
    
    def add_recurring_expense(self, category, subcategory, amount, day_of_month, 
                            start_year, start_month, duration_type, duration_months=None, comment=''):
        """Dodaje nowy wydatek cykliczny"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO budget_recurring_expense 
                (category, subcategory, amount, day_of_month, start_year, start_month, 
                 duration_type, duration_months, comment, active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ''', (category, subcategory, amount, day_of_month, start_year, start_month,
                  duration_type, duration_months, comment))
            conn.commit()
            logger.info(f"Dodano wydatek cykliczny: {category}/{subcategory}")
    
    def get_recurring_expenses(self):
        """Pobiera wszystkie aktywne wydatki cykliczne"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM budget_recurring_expense 
                WHERE active = 1
                ORDER BY category, subcategory
            ''')
            return [dict(row) for row in cursor.fetchall()]
    
    def update_recurring_expense(self, recurring_id, category, subcategory, amount, day_of_month,
                                duration_type, duration_months=None, comment=''):
        """Aktualizuje wydatek cykliczny"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE budget_recurring_expense 
                SET category = ?, subcategory = ?, amount = ?, day_of_month = ?,
                    duration_type = ?, duration_months = ?, comment = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (category, subcategory, amount, day_of_month, duration_type, 
                  duration_months, comment, recurring_id))
            conn.commit()
            logger.info(f"Zaktualizowano wydatek cykliczny ID: {recurring_id}")
    
    def delete_recurring_expense(self, recurring_id):
        """Usuwa (dezaktywuje) wydatek cykliczny"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE budget_recurring_expense 
                SET active = 0, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (recurring_id,))
            conn.commit()
            logger.info(f"Usunięto wydatek cykliczny ID: {recurring_id}")
    
    def generate_recurring_expenses_for_month(self, year, month):
        """Generuje wydatki dla danego miesiąca na podstawie reguł cyklicznych"""
        recurring_expenses = self.get_recurring_expenses()
        generated_count = 0
        
        for rec in recurring_expenses:
            # Sprawdź czy miesiąc jest w zakresie
            start_date = (rec['start_year'], rec['start_month'])
            current_date = (year, month)
            
            if current_date < start_date:
                continue  # Jeszcze nie rozpoczął się
            
            # Sprawdź czy nie przekroczono limitu czasu
            if rec['duration_type'] == 'months' and rec['duration_months'] is not None:
                months_passed = (year - rec['start_year']) * 12 + (month - rec['start_month'])
                if months_passed >= rec['duration_months']:
                    continue  # Przekroczono czas trwania
            
            # Sprawdź czy wydatek już nie istnieje w tym miesiącu
            with self.pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT COUNT(*) as count FROM budget_expense
                    WHERE year = ? AND month = ? AND day = ? 
                    AND category = ? AND subcategory = ?
                ''', (year, month, rec['day_of_month'], rec['category'], rec['subcategory']))
                
                if cursor.fetchone()['count'] > 0:
                    continue  # Wydatek już istnieje
            
            # Generuj wydatek
            self.add_budget_expense(
                year, month, rec['day_of_month'],
                rec['category'], rec['subcategory'],
                rec['amount'], rec['comment']
            )
            generated_count += 1
        
        if generated_count > 0:
            logger.info(f"Wygenerowano {generated_count} wydatków cyklicznych dla {month}/{year}")
        
        return generated_count
    
    # ============================================================
    # METODY CACHE CENOWEGO (HYBRYDOWE ŁADOWANIE)
    # ============================================================
    
    def get_cached_price(self, ticker, max_age_minutes=60):
        """
        Pobiera cenę z cache jeśli jest świeża
        
        Args:
            ticker: Symbol spółki
            max_age_minutes: Maksymalny wiek cache w minutach
            
        Returns:
            dict z ceną i metadanymi lub None jeśli cache nieważny
        """
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT ticker, last_price, last_update, company_name, currency
                FROM price_cache
                WHERE ticker = ?
                AND datetime(last_update) > datetime('now', ?)
            ''', (ticker, f'-{max_age_minutes} minutes'))
            
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    
    def update_price_cache(self, ticker, price, company_name=None, currency='USD'):
        """
        Aktualizuje cache cenowy dla tickera
        
        Args:
            ticker: Symbol spółki
            price: Aktualna cena
            company_name: Nazwa firmy (opcjonalnie)
            currency: Waluta
        """
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO price_cache 
                (ticker, last_price, last_update, company_name, currency)
                VALUES (?, ?, datetime('now'), ?, ?)
            ''', (ticker, price, company_name, currency))
            conn.commit()
    
    def update_price_cache_batch(self, price_data):
        """
        Aktualizuje wiele cen naraz (batch update)
        
        Args:
            price_data: Lista dict z kluczami: ticker, price, company_name, currency
        """
        if not price_data:
            return
            
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany('''
                INSERT OR REPLACE INTO price_cache 
                (ticker, last_price, last_update, company_name, currency)
                VALUES (?, ?, datetime('now'), ?, ?)
            ''', [(d['ticker'], d['price'], d.get('company_name'), d.get('currency', 'USD')) 
                  for d in price_data])
            conn.commit()
            logger.info(f"✅ Zaktualizowano cache dla {len(price_data)} tickerów")
    
    def get_positions_with_cache(self, currency='USD'):
        """
        Pobiera pozycje wraz z cenami z cache (jeśli dostępne)
        INSTANT LOAD - nie czeka na API!
        
        Args:
            currency: Waluta pozycji
            
        Returns:
            Lista pozycji z cached_price i cache_age_minutes
        """
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    p.id,
                    p.ticker,
                    p.quantity,
                    p.buy_price as purchase_price,
                    p.purchase_date,
                    p.currency,
                    p.instrument_type,
                    p.leverage,
                    p.direction,
                    p.swap_daily,
                    p.dividend,
                    p.alert_price,
                    p.usd_rate,
                    p.eur_rate,
                    pc.last_price as cached_price,
                    pc.last_update as cache_update,
                    pc.company_name,
                    CAST((julianday('now') - julianday(pc.last_update)) * 24 * 60 AS INTEGER) as cache_age_minutes
                FROM positions p
                LEFT JOIN price_cache pc ON p.ticker = pc.ticker
                WHERE p.currency = ?
                ORDER BY p.purchase_date DESC
            ''', (currency,))
            
            results = cursor.fetchall()
            return [dict(row) for row in results]
    
    def clear_old_cache(self, max_age_days=30):
        """
        Usuwa stary cache (dla tickerów które nie są już w portfolio ani watchlist)
        
        Args:
            max_age_days: Usuwa cache starszy niż X dni
        """
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            
            # Usuń cache dla tickerów które nie są w positions ani watchlist
            cursor.execute('''
                DELETE FROM price_cache
                WHERE ticker NOT IN (SELECT ticker FROM positions)
                AND ticker NOT IN (SELECT ticker FROM watchlist)
                AND datetime(last_update) < datetime('now', ?)
            ''', (f'-{max_age_days} days',))
            
            deleted = cursor.rowcount
            conn.commit()
            
            if deleted > 0:
                logger.info(f"🗑️ Usunięto {deleted} starych wpisów z cache")
            
            return deleted
    
    def get_cache_statistics(self):
        """Zwraca statystyki cache"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_cached,
                    COUNT(CASE WHEN datetime(last_update) > datetime('now', '-1 hour') 
                          THEN 1 END) as fresh_1h,
                    COUNT(CASE WHEN datetime(last_update) > datetime('now', '-24 hours') 
                          THEN 1 END) as fresh_24h,
                    MIN(last_update) as oldest_cache,
                    MAX(last_update) as newest_cache
                FROM price_cache
            ''')
            
            return dict(cursor.fetchone())
    
    def optimize_database(self):
        """
        Optymalizuje bazę danych - usuwa fragmentację, przebudowuje indeksy
        UWAGA: Może zająć kilka sekund dla dużych baz
        Uruchamiaj co miesiąc lub po wielu operacjach
        """
        logger.info("🔧 Rozpoczynam optymalizację bazy danych...")
        start_time = time.time()
        
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                # 1. ANALYZE - Aktualizuje statystyki zapytań (query planner)
                logger.info("  📊 Aktualizacja statystyk...")
                cursor.execute('ANALYZE')
                
                # 2. REINDEX - Przebudowuje wszystkie indeksy
                logger.info("  🔄 Przebudowa indeksów...")
                cursor.execute('REINDEX')
                
                # 3. VACUUM - Usuwa fragmentację i zmniejsza rozmiar pliku
                # UWAGA: To może zająć chwilę!
                logger.info("  🗜️ Usuwanie fragmentacji (może chwilę potrwać)...")
                cursor.execute('VACUUM')
                
                # 4. OPTIMIZE - SQLite auto-optymalizacja
                logger.info("  ⚡ Auto-optymalizacja...")
                cursor.execute('PRAGMA optimize')
                
                conn.commit()
                
                elapsed = time.time() - start_time
                logger.info(f"✅ Optymalizacja zakończona w {elapsed:.2f}s")
                logger.info("   Baza danych jest teraz super szybka!")
                
                return True
                
            except Exception as e:
                logger.error(f"❌ Błąd podczas optymalizacji: {e}")
                return False
    
    def get_database_stats(self):
        """Zwraca statystyki bazy danych"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            
            # Rozmiar bazy
            cursor.execute("SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size()")
            db_size = cursor.fetchone()[0]
            
            # Liczba tabel
            cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
            table_count = cursor.fetchone()[0]
            
            # Liczba indeksów
            cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='index'")
            index_count = cursor.fetchone()[0]
            
            # Liczba rekordów w głównych tabelach
            cursor.execute("SELECT COUNT(*) FROM positions")
            positions_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM history")
            history_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM price_cache")
            cache_count = cursor.fetchone()[0]
            
            return {
                'size_mb': db_size / (1024 * 1024),
                'tables': table_count,
                'indexes': index_count,
                'positions': positions_count,
                'history': history_count,
                'cached_prices': cache_count
            }
    
    def close(self):
        """Zamyka connection pool"""
        self.pool.close_all()
        logger.info("Database zamknięta")
    
    # ============================================================
    # METODY DLA STRATEGII DO ROZEGRANIA
    # ============================================================
    
    def add_strategy_to_play(self, ticker, strategy_percent, direction, levels):
        """Dodaje strategię do rozegrania"""
        import json
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO strategy_to_play 
                (ticker, strategy_percent, direction, levels)
                VALUES (?, ?, ?, ?)
            ''', (ticker.upper(), strategy_percent, direction, json.dumps(levels)))
            conn.commit()
            logger.info(f"Dodano strategię do rozegrania: {ticker}")
    
    def get_strategies_to_play(self):
        """Pobiera wszystkie strategie do rozegrania"""
        import json
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM strategy_to_play ORDER BY ticker')
            rows = cursor.fetchall()
            result = []
            for row in rows:
                data = dict(row)
                data['levels'] = json.loads(data['levels'])
                data['opened_levels'] = json.loads(data.get('opened_levels', '[]'))
                result.append(data)
            return result
    
    def mark_level_as_opened(self, strategy_id, level_number):
        """Oznacza poziom jako otwarty"""
        import json
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            
            # Pobierz obecne opened_levels
            cursor.execute('SELECT opened_levels FROM strategy_to_play WHERE id = ?', (strategy_id,))
            row = cursor.fetchone()
            
            if row:
                opened_levels = json.loads(row['opened_levels'] if row['opened_levels'] else '[]')
                
                # Dodaj nowy poziom jeśli jeszcze nie istnieje
                if level_number not in opened_levels:
                    opened_levels.append(level_number)
                
                # Zapisz zaktualizowaną listę
                cursor.execute(
                    'UPDATE strategy_to_play SET opened_levels = ? WHERE id = ?',
                    (json.dumps(opened_levels), strategy_id)
                )
                conn.commit()
                logger.info(f"Oznaczono poziom {level_number} jako otwarty dla strategii ID: {strategy_id}")
    
    def delete_strategy_to_play(self, strategy_id):
        """Usuwa strategię do rozegrania"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM strategy_to_play WHERE id = ?', (strategy_id,))
            conn.commit()
            logger.info(f"Usunięto strategię do rozegrania ID: {strategy_id}")
    
    def add_strategy_playing(self, ticker, strategy_percent, buy_price, quantity, close_price, direction='Wzrosty'):
        """Dodaje aktywnie rozgrywaną strategię"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO strategy_playing 
                (ticker, strategy_percent, buy_price, quantity, close_price, direction)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (ticker.upper(), strategy_percent, buy_price, quantity, close_price, direction))
            strategy_id = cursor.lastrowid
            conn.commit()
            logger.info(f"Dodano rozgrywaną strategię: {ticker} (kierunek: {direction})")
            return strategy_id
    
    def get_strategies_playing(self):
        """Pobiera wszystkie aktywnie rozgrywane strategie"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM strategy_playing ORDER BY ticker')
            return [dict(row) for row in cursor.fetchall()]
    
    def delete_strategy_playing(self, strategy_id):
        """Usuwa rozgrywaną strategię"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM strategy_playing WHERE id = ?', (strategy_id,))
            conn.commit()
            logger.info(f"Usunięto rozgrywaną strategię ID: {strategy_id}")

    # ============================================================
    # MODUŁ MEDIA - Naprawione metody (connection pool)
    # ============================================================
    
    # ============================================================
    # MODUŁ MEDIA - POPRAWIONA WERSJA (context manager)
    # ============================================================
    
    def create_media_tables(self):
        """Tworzy tabele dla modułu MEDIA"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS utility_readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    utility_type TEXT NOT NULL,
                    reading_date DATE NOT NULL,
                    reading_value REAL NOT NULL,
                    unit_cost REAL DEFAULT 0,
                    comment TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(utility_type, reading_date)
                )
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_utility_type 
                ON utility_readings(utility_type)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_reading_date 
                ON utility_readings(reading_date)
            """)
            
            conn.commit()
            logger.info("✅ Tabele modułu MEDIA zostały utworzone")
    
    def add_utility_reading(self, utility_type, reading_date, reading_value, unit_cost=0, comment=''):
        """Dodaje odczyt licznika"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                cursor.execute("""
                    INSERT INTO utility_readings 
                    (utility_type, reading_date, reading_value, unit_cost, comment)
                    VALUES (?, ?, ?, ?, ?)
                """, (utility_type, reading_date, reading_value, unit_cost, comment))
                
                conn.commit()
                logger.info(f"Dodano odczyt: {utility_type} - {reading_value} z dnia {reading_date}")
                return cursor.lastrowid
            except Exception as e:
                conn.rollback()
                logger.error(f"Błąd dodawania odczytu: {e}")
                raise
    
    def update_utility_reading(self, reading_id, reading_date, reading_value, unit_cost, comment):
        """Aktualizuje odczyt licznika"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                cursor.execute("""
                    UPDATE utility_readings
                    SET reading_date = ?,
                        reading_value = ?,
                        unit_cost = ?,
                        comment = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (reading_date, reading_value, unit_cost, comment, reading_id))
                
                conn.commit()
                logger.info(f"Zaktualizowano odczyt ID: {reading_id}")
            except Exception as e:
                conn.rollback()
                logger.error(f"Błąd aktualizacji odczytu: {e}")
                raise
    
    def delete_utility_reading(self, reading_id):
        """Usuwa odczyt licznika"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("DELETE FROM utility_readings WHERE id = ?", (reading_id,))
                conn.commit()
                logger.info(f"Usunięto odczyt ID: {reading_id}")
            except Exception as e:
                conn.rollback()
                logger.error(f"Błąd usuwania odczytu: {e}")
                raise
    
    def get_utility_readings(self, utility_type, limit=None):
        """Pobiera odczyty dla danego medium"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            
            query = """
                SELECT 
                    r1.id,
                    r1.utility_type,
                    r1.reading_date,
                    r1.reading_value,
                    r1.unit_cost,
                    r1.comment,
                    COALESCE(r1.reading_value - r2.reading_value, 0) as consumption
                FROM utility_readings r1
                LEFT JOIN utility_readings r2 ON 
                    r2.utility_type = r1.utility_type AND
                    r2.reading_date = (
                        SELECT MAX(reading_date) 
                        FROM utility_readings 
                        WHERE utility_type = r1.utility_type 
                        AND reading_date < r1.reading_date
                    )
                WHERE r1.utility_type = ?
                ORDER BY r1.reading_date DESC
            """
            
            if limit:
                query += f" LIMIT {limit}"
            
            cursor.execute(query, (utility_type,))
            
            columns = [description[0] for description in cursor.description]
            results = []
            
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
            
            return results
    
    def get_all_utility_readings(self, limit=100):
        """Pobiera wszystkie odczyty"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            
            query = """
                SELECT 
                    r1.id,
                    r1.utility_type,
                    r1.reading_date,
                    r1.reading_value,
                    r1.unit_cost,
                    r1.comment,
                    COALESCE(r1.reading_value - r2.reading_value, 0) as consumption
                FROM utility_readings r1
                LEFT JOIN utility_readings r2 ON 
                    r2.utility_type = r1.utility_type AND
                    r2.reading_date = (
                        SELECT MAX(reading_date) 
                        FROM utility_readings 
                        WHERE utility_type = r1.utility_type 
                        AND reading_date < r1.reading_date
                    )
                ORDER BY r1.reading_date DESC
                LIMIT ?
            """
            
            cursor.execute(query, (limit,))
            
            columns = [description[0] for description in cursor.description]
            results = []
            
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
            
            return results
    
    def get_last_utility_reading(self, utility_type):
        """Pobiera ostatni odczyt dla danego medium"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    id, utility_type, reading_date, reading_value, 
                    unit_cost, comment
                FROM utility_readings
                WHERE utility_type = ?
                ORDER BY reading_date DESC
                LIMIT 1
            """, (utility_type,))
            
            row = cursor.fetchone()
            
            if row:
                columns = [description[0] for description in cursor.description]
                return dict(zip(columns, row))
            
            return None
    
    def get_utility_consumption_data(self, utility_type, months=None):
        """Pobiera dane o zużyciu dla wykresu - NAPRAWIONA"""
        from datetime import datetime, timedelta
        
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            
            query = """
                SELECT 
                    strftime('%Y-%m', reading_date) as month,
                    MAX(reading_value) as reading_value,
                    AVG(unit_cost) as avg_unit_cost
                FROM utility_readings
                WHERE utility_type = ?
            """
            
            params = [utility_type]
            
            if months:
                date_limit = (datetime.now() - timedelta(days=months*31)).strftime('%Y-%m-%d')
                query += " AND reading_date >= ?"
                params.append(date_limit)
            
            query += """
                GROUP BY month
                ORDER BY month
            """
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            if not rows:
                return []
            
            results = []
            month_names = ['Sty', 'Lut', 'Mar', 'Kwi', 'Maj', 'Cze', 
                          'Lip', 'Sie', 'Wrz', 'Paź', 'Lis', 'Gru']
            
            prev_reading = None
            for row in rows:
                month = row[0]
                current_reading = row[1]
                avg_unit_cost = row[2] if row[2] else 0
                
                if prev_reading is not None:
                    consumption = current_reading - prev_reading
                    
                    if consumption > 0:
                        year, m = month.split('-')
                        month_label = f"{month_names[int(m)-1]} {year}"
                        
                        results.append({
                            'month': month,
                            'month_label': month_label,
                            'consumption': consumption,
                            'avg_unit_cost': avg_unit_cost,
                            'cost': consumption * avg_unit_cost
                        })
                
                prev_reading = current_reading
            
            return results
    
    def get_utility_stats(self, utility_type):
        """Pobiera statystyki dla danego medium - NAPRAWIONA"""
        from datetime import datetime, timedelta
        
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT COUNT(*) FROM utility_readings WHERE utility_type = ?
            """, (utility_type,))
            count = cursor.fetchone()[0]
            
            if count == 0:
                return {
                    'count': 0,
                    'last_reading': 0,
                    'current_month_usage': 0,
                    'avg_monthly': 0,
                    'trend_text': 'Brak danych'
                }
            
            cursor.execute("""
                SELECT reading_value 
                FROM utility_readings 
                WHERE utility_type = ?
                ORDER BY reading_date DESC 
                LIMIT 1
            """, (utility_type,))
            last_reading = cursor.fetchone()[0]
            
            current_month = datetime.now().strftime('%Y-%m')
            
            cursor.execute("""
                SELECT MAX(reading_value)
                FROM utility_readings
                WHERE utility_type = ? 
                AND strftime('%Y-%m', reading_date) = ?
            """, (utility_type, current_month))
            
            current_month_reading = cursor.fetchone()[0]
            
            cursor.execute("""
                SELECT reading_value
                FROM utility_readings
                WHERE utility_type = ? 
                AND strftime('%Y-%m', reading_date) < ?
                ORDER BY reading_date DESC
                LIMIT 1
            """, (utility_type, current_month))
            
            prev_result = cursor.fetchone()
            prev_month_reading = prev_result[0] if prev_result else 0
            
            current_month_usage = current_month_reading - prev_month_reading if current_month_reading and prev_month_reading else 0
            
            six_months_ago = (datetime.now() - timedelta(days=180)).strftime('%Y-%m-%d')
            
            cursor.execute("""
                SELECT 
                    strftime('%Y-%m', reading_date) as month,
                    MAX(reading_value) as reading
                FROM utility_readings
                WHERE utility_type = ?
                AND reading_date >= ?
                GROUP BY month
                ORDER BY month
            """, (utility_type, six_months_ago))
            
            monthly_readings = cursor.fetchall()
            
            consumptions = []
            prev_reading = None
            for row in monthly_readings:
                current_reading = row[1]
                if prev_reading is not None:
                    consumption = current_reading - prev_reading
                    if consumption > 0:
                        consumptions.append(consumption)
                prev_reading = current_reading
            
            avg_monthly = sum(consumptions) / len(consumptions) if consumptions else 0
            
            if avg_monthly > 0 and current_month_usage > 0:
                diff_percent = ((current_month_usage - avg_monthly) / avg_monthly) * 100
                if diff_percent > 10:
                    trend_text = f"📈 +{diff_percent:.1f}% powyżej średniej"
                elif diff_percent < -10:
                    trend_text = f"📉 {diff_percent:.1f}% poniżej średniej"
                else:
                    trend_text = "➡️ Stabilne"
            elif len(consumptions) < 2:
                trend_text = "➡️ Za mało danych"
            else:
                trend_text = "➡️ Brak zużycia w tym miesiącu"
            
            return {
                'count': count,
                'last_reading': last_reading,
                'current_month_usage': current_month_usage,
                'avg_monthly': avg_monthly,
                'trend_text': trend_text
            }
    
    def get_utility_monthly_summary(self, months=3):
        """Pobiera podsumowanie miesięczne dla wszystkich mediów"""
        from collections import defaultdict
        
        all_data = {}
        for utility in ["💧 Woda", "⚡ Prąd", "🔥 Gaz"]:
            all_data[utility] = self.get_utility_consumption_data(utility, months)
        
        months_dict = defaultdict(dict)
        
        for utility, data_list in all_data.items():
            for item in data_list:
                month = item['month']
                months_dict[month][utility] = {
                    'consumption': item['consumption'],
                    'cost': item['cost']
                }
                if 'month_label' not in months_dict[month]:
                    months_dict[month]['month_label'] = item['month_label']
        
        result = []
        for month in sorted(months_dict.keys()):
            data = months_dict[month]
            data['month'] = month
            result.append(data)
        
        return result
    
    # ============================================================
    # ZARZĄDZANIE USTAWIENIAMI APLIKACJI
    # ============================================================
    
    def get_setting(self, key, default='true'):
        """Pobiera wartość ustawienia"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
            result = cursor.fetchone()
            return result[0] if result else default
    
    def set_setting(self, key, value):
        """Ustawia wartość ustawienia"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO app_settings (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            """, (key, value))
            conn.commit()
            logger.info(f"Zaktualizowano ustawienie: {key} = {value}")
    
    def is_module_enabled(self, module_name):
        """Sprawdza czy moduł jest włączony"""
        key = f"module_{module_name}_enabled"
        value = self.get_setting(key, 'true')
        return value.lower() == 'true'
    
    def set_module_enabled(self, module_name, enabled):
        """Włącza lub wyłącza moduł"""
        key = f"module_{module_name}_enabled"
        value = 'true' if enabled else 'false'
        self.set_setting(key, value)
    
    # ============================================================
    # ZARZĄDZANIE AUTORYZACJĄ I HASŁAMI
    # ============================================================
    
    def is_auth_enabled(self):
        """Sprawdza czy autoryzacja jest włączona"""
        value = self.get_setting('auth_enabled', 'false')
        return value.lower() == 'true'
    
    def set_auth_enabled(self, enabled):
        """Włącza lub wyłącza autoryzację"""
        value = 'true' if enabled else 'false'
        self.set_setting('auth_enabled', value)
    
    def has_password_set(self):
        """Sprawdza czy hasło zostało już ustawione"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM auth_settings WHERE id = 1")
            count = cursor.fetchone()[0]
            return count > 0
    
    def create_password(self, password, recovery_key):
        """Tworzy nowe hasło i recovery key (pierwsze uruchomienie)"""
        import bcrypt
        
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            
            # Hash hasła (12 rounds)
            password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=12))
            
            # Hash recovery key (12 rounds)
            recovery_hash = bcrypt.hashpw(recovery_key.encode('utf-8'), bcrypt.gensalt(rounds=12))
            
            # Zapisz w bazie
            cursor.execute("""
                INSERT OR REPLACE INTO auth_settings 
                (id, password_hash, recovery_key_hash, failed_attempts, locked_until, updated_at)
                VALUES (1, ?, ?, 0, NULL, CURRENT_TIMESTAMP)
            """, (password_hash, recovery_hash))
            
            conn.commit()
            
            # Włącz autoryzację
            self.set_auth_enabled(True)
            
            logger.info("Hasło zostało ustawione pomyślnie")
    
    def verify_password(self, password):
        """Weryfikuje hasło"""
        import bcrypt
        from datetime import datetime
        
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            
            # Sprawdź czy konto jest zablokowane
            cursor.execute("SELECT locked_until, failed_attempts FROM auth_settings WHERE id = 1")
            result = cursor.fetchone()
            
            if not result:
                return False, "Hasło nie zostało ustawione"
            
            locked_until, failed_attempts = result
            
            # Sprawdź blokadę
            if locked_until:
                lock_time = datetime.fromisoformat(locked_until)
                if datetime.now() < lock_time:
                    remaining = (lock_time - datetime.now()).total_seconds() / 60
                    return False, f"Konto zablokowane na {remaining:.0f} minut"
                else:
                    # Blokada wygasła - resetuj licznik
                    cursor.execute("""
                        UPDATE auth_settings 
                        SET locked_until = NULL, failed_attempts = 0
                        WHERE id = 1
                    """)
                    conn.commit()
            
            # Pobierz hash hasła
            cursor.execute("SELECT password_hash FROM auth_settings WHERE id = 1")
            result = cursor.fetchone()
            
            if not result:
                return False, "Błąd weryfikacji"
            
            password_hash = result[0]
            
            # Weryfikuj hasło
            try:
                if bcrypt.checkpw(password.encode('utf-8'), password_hash):
                    # Hasło poprawne - resetuj licznik
                    cursor.execute("""
                        UPDATE auth_settings 
                        SET failed_attempts = 0, locked_until = NULL
                        WHERE id = 1
                    """)
                    conn.commit()
                    logger.info("Pomyślne logowanie")
                    return True, "Sukces"
                else:
                    # Hasło niepoprawne - zwiększ licznik
                    return self._handle_failed_login(cursor, conn, failed_attempts)
            except Exception as e:
                logger.error(f"Błąd weryfikacji hasła: {e}")
                return False, "Błąd weryfikacji"
    
    def _handle_failed_login(self, cursor, conn, current_attempts):
        """Obsługuje nieudaną próbę logowania"""
        from datetime import datetime, timedelta
        
        new_attempts = current_attempts + 1
        max_attempts = int(self.get_setting('auth_lock_after_attempts', '5'))
        lock_duration = int(self.get_setting('auth_lock_duration_minutes', '15'))
        
        if new_attempts >= max_attempts:
            # Zablokuj konto
            locked_until = datetime.now() + timedelta(minutes=lock_duration)
            cursor.execute("""
                UPDATE auth_settings 
                SET failed_attempts = ?, locked_until = ?
                WHERE id = 1
            """, (new_attempts, locked_until.isoformat()))
            conn.commit()
            logger.warning(f"Konto zablokowane po {new_attempts} nieudanych próbach")
            return False, f"Zbyt wiele nieudanych prób. Konto zablokowane na {lock_duration} minut."
        else:
            # Zwiększ licznik
            cursor.execute("""
                UPDATE auth_settings 
                SET failed_attempts = ?
                WHERE id = 1
            """, (new_attempts,))
            conn.commit()
            remaining = max_attempts - new_attempts
            return False, f"Niepoprawne hasło. Pozostało prób: {remaining}"
    
    def verify_recovery_key(self, recovery_key):
        """Weryfikuje recovery key"""
        import bcrypt
        
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT recovery_key_hash FROM auth_settings WHERE id = 1")
            result = cursor.fetchone()
            
            if not result:
                return False
            
            recovery_hash = result[0]
            
            try:
                return bcrypt.checkpw(recovery_key.encode('utf-8'), recovery_hash)
            except Exception as e:
                logger.error(f"Błąd weryfikacji recovery key: {e}")
                return False
    
    def change_password(self, new_password, recovery_key=None):
        """Zmienia hasło (opcjonalnie generuje nowy recovery key)"""
        import bcrypt
        
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            
            # Hash nowego hasła
            password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt(rounds=12))
            
            if recovery_key:
                # Nowy recovery key również
                recovery_hash = bcrypt.hashpw(recovery_key.encode('utf-8'), bcrypt.gensalt(rounds=12))
                cursor.execute("""
                    UPDATE auth_settings 
                    SET password_hash = ?, recovery_key_hash = ?, 
                        failed_attempts = 0, locked_until = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1
                """, (password_hash, recovery_hash))
            else:
                # Tylko hasło
                cursor.execute("""
                    UPDATE auth_settings 
                    SET password_hash = ?, failed_attempts = 0, locked_until = NULL, 
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1
                """, (password_hash,))
            
            conn.commit()
            logger.info("Hasło zostało zmienione")
    
    def disable_auth(self):
        """Wyłącza autoryzację i usuwa hasła"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM auth_settings WHERE id = 1")
            conn.commit()
            self.set_auth_enabled(False)
            logger.info("Autoryzacja wyłączona")
    
    def get_failed_attempts(self):
        """Pobiera liczbę nieudanych prób logowania"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT failed_attempts FROM auth_settings WHERE id = 1")
            result = cursor.fetchone()
            return result[0] if result else 0
    
    