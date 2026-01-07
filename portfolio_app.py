import sys
import os
import logging
import csv
import re
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from functools import wraps
from typing import Dict, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QTabWidget, QTableWidget, QTableWidgetItem,
                             QPushButton, QLabel, QLineEdit, QDialog, QFormLayout,
                             QMessageBox, QHeaderView, QComboBox, QCompleter, QDateEdit,
                             QFileDialog, QProgressBar, QCheckBox, QStackedWidget, QScrollArea)
from PyQt5.QtCore import Qt, QTimer, QStringListModel, QDate, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QFont
import yfinance as yf
import requests
import pandas as pd
from database import Database
from budget_module import BudgetWidget
from media_module import MediaWidget
from auth_module import (SetupPasswordDialog, LoginDialog, RecoveryDialog, 
                         ChangePasswordDialog, PasswordManager)

# Windows-specific imports dla session monitoring
if sys.platform == 'win32':
    try:
        import win32api
        import win32con
        import win32gui
        import ctypes
        from ctypes import wintypes
    except ImportError:
        logger.warning("pywin32 nie zainstalowany - funkcje Windows lock będą niedostępne")


# Funkcja do obsługi ścieżek w .exe
def resource_path(relative_path):
    """
    Zwraca poprawną ścieżkę do zasobów zarówno dla .exe jak i normalnego uruchomienia
    
    Args:
        relative_path: Relatywna ścieżka do zasobu
        
    Returns:
        Absolutna ścieżka do zasobu
    """
    try:
        # PyInstaller tworzy folder tymczasowy i przechowuje ścieżkę w _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    
    return os.path.join(base_path, relative_path)

# Stałe aplikacji
AUTO_REFRESH_INTERVAL_MS = 3600000  # 1 godzina w milisekundach
NETWORK_TIMEOUT_SECONDS = 3
MAX_TICKER_LENGTH = 10
VALID_CURRENCIES = ('USD', 'PLN')
YAHOO_SEARCH_API_URL = "https://query2.finance.yahoo.com/v1/finance/search"
SEARCH_DEBOUNCE_MS = 300
ALERT_COLOR_YELLOW = QColor(255, 255, 150)
ALERT_COLOR_GREEN = QColor(220, 252, 231)

# Regex dla walidacji tickera (litery, cyfry, kropka, myślnik)
TICKER_PATTERN = re.compile(r'^[A-Z0-9.\-]{1,10}$')

# Klasa cache dla cen akcji
class PriceCache:
    """Thread-safe cache dla cen akcji z TTL (Time To Live)"""
    
    def __init__(self, ttl_minutes: int = 5):
        """
        Inicjalizuje cache.
        
        Args:
            ttl_minutes: Czas życia cache w minutach (domyślnie 5)
        """
        self._cache: Dict[str, Tuple[float, datetime]] = {}
        self._ttl = timedelta(minutes=ttl_minutes)
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0
    
    def get(self, ticker: str) -> Optional[float]:
        """
        Pobiera cenę z cache jeśli jest aktualna.
        
        Args:
            ticker: Symbol spółki
            
        Returns:
            Cena lub None jeśli nie ma w cache lub jest nieaktualna
        """
        with self._lock:
            if ticker in self._cache:
                price, timestamp = self._cache[ticker]
                if datetime.now() - timestamp < self._ttl:
                    self.hits += 1
                    return price
            self.misses += 1
            return None
    
    def set(self, ticker: str, price: float) -> None:
        """
        Zapisuje cenę do cache.
        
        Args:
            ticker: Symbol spółki
            price: Cena do zapisania
        """
        with self._lock:
            self._cache[ticker] = (price, datetime.now())
    
    def clear(self) -> None:
        """Czyści cały cache"""
        with self._lock:
            self._cache.clear()
            self.hits = 0
            self.misses = 0
    
    def get_stats(self) -> str:
        """Zwraca statystyki cache"""
        total = self.hits + self.misses
        if total == 0:
            return "Cache: Brak requestów"
        hit_rate = (self.hits / total) * 100
        return f"Cache: {self.hits}/{total} trafień ({hit_rate:.1f}%)"


# Decorator dla retry mechanism
def retry_on_failure(max_attempts: int = 3, delay: float = 1.0, 
                     backoff: float = 2.0, exceptions: tuple = (Exception,)):
    """
    Decorator dla automatycznego retry z exponential backoff.
    
    Args:
        max_attempts: Maksymalna liczba prób
        delay: Początkowe opóźnienie w sekundach
        backoff: Mnożnik opóźnienia dla kolejnych prób
        exceptions: Tuple wyjątków do złapania
        
    Returns:
        Dekorowana funkcja z retry logic
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        logger.warning(
                            f"Próba {attempt + 1}/{max_attempts} nie powiodła się "
                            f"dla {func.__name__}: {e}. Retry za {current_delay:.1f}s..."
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(
                            f"Wszystkie {max_attempts} próby nie powiodły się "
                            f"dla {func.__name__}: {e}"
                        )
            
            raise last_exception
        return wrapper
    return decorator


# Funkcje pomocnicze
def sanitize_ticker(ticker: str) -> str:
    """
    Sanityzuje i waliduje ticker
    
    Args:
        ticker: Symbol spółki do sanityzacji
        
    Returns:
        Oczyszczony ticker
        
    Raises:
        ValueError: Jeśli ticker jest nieprawidłowy
    """
    if not ticker or not isinstance(ticker, str):
        raise ValueError("Ticker musi być niepustym tekstem")
    
    # Usuń białe znaki i zamień na uppercase
    ticker = ticker.strip().upper()
    
    # Sprawdź długość
    if len(ticker) > MAX_TICKER_LENGTH:
        raise ValueError(f"Ticker nie może być dłuższy niż {MAX_TICKER_LENGTH} znaków")
    
    # Waliduj znaki
    if not TICKER_PATTERN.match(ticker):
        raise ValueError("Ticker może zawierać tylko litery, cyfry, kropki i myślniki")
    
    return ticker

def safe_float_convert(value: str, field_name: str = "wartość") -> float:
    """
    Bezpiecznie konwertuje string na float z walidacją
    
    Args:
        value: Wartość do konwersji
        field_name: Nazwa pola (do komunikatów błędów)
        
    Returns:
        Skonwertowana wartość
        
    Raises:
        ValueError: Jeśli konwersja nie powiodła się
    """
    try:
        result = float(value)
        if result <= 0:
            raise ValueError(f"{field_name} musi być większa od 0")
        return result
    except (ValueError, TypeError) as e:
        raise ValueError(f"Nieprawidłowa {field_name}: {value}")

def safe_file_path(file_path: str) -> Path:
    """
    Sprawdza czy ścieżka pliku jest bezpieczna (zapobiega path traversal)
    
    Args:
        file_path: Ścieżka do sprawdzenia
        
    Returns:
        Bezpieczna ścieżka jako Path object
        
    Raises:
        ValueError: Jeśli ścieżka jest niebezpieczna
    """
    path = Path(file_path).resolve()
    
    # Sprawdź czy ścieżka nie zawiera podejrzanych elementów
    if '..' in path.parts:
        raise ValueError("Ścieżka zawiera niedozwolone elementy")
    
    return path

# Konfiguracja logowania
def setup_logging():
    """Konfiguruje system logowania do pliku"""
    # Określ katalog bazowy - dla .exe i normalnego uruchomienia
    if getattr(sys, 'frozen', False):
        # Uruchomione jako .exe (PyInstaller)
        base_dir = os.path.dirname(sys.executable)
    else:
        # Uruchomione jako skrypt Python
        base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Utwórz folder Logs jeśli nie istnieje
    logs_dir = os.path.join(base_dir, 'Logs')
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
    
    # Nazwa pliku z datą
    log_filename = f"Log_{datetime.now().strftime('%Y-%m-%d')}.txt"
    log_path = os.path.join(logs_dir, log_filename)
    
    # Konfiguracja formatowania
    logging.basicConfig(
        level=logging.WARNING,  # Tylko WARNING, ERROR i CRITICAL
        format='%(asctime)s - %(levelname)s - %(funcName)s - %(message)s',
        handlers=[
            logging.FileHandler(log_path, encoding='utf-8'),
            logging.StreamHandler()  # Też wyświetla w konsoli
        ]
    )
    
    logger = logging.getLogger(__name__)
    # Logujemy tylko krytyczną informację o starcie
    logger.warning(f"Portfolio Monitor uruchomiony - Log: {log_path}")
    
    return logger

# Inicjalizuj logger
logger = setup_logging()

class AddPositionDialog(QDialog):
    def __init__(self, currency, parent=None, prefill_ticker=None, prefill_data=None):
        super().__init__(parent)
        self.currency = currency
        self.position_data = None
        self.ticker_suggestions = []
        self.prefill_ticker = prefill_ticker  # Ticker do automatycznego wpisania
        self.prefill_data = prefill_data  # Wszystkie dane do wypełnienia formularza
        self.init_ui()
    
    @retry_on_failure(max_attempts=3, delay=1.0, backoff=2.0, 
                      exceptions=(requests.RequestException, requests.Timeout))
    def search_tickers(self, query):
        """Wyszukuje tickery w Yahoo Finance z retry mechanism"""
        if len(query) < 1:
            return []
        
        # Sanityzuj query
        try:
            query = sanitize_ticker(query)
        except ValueError as e:
            logger.warning(f"Nieprawidłowy ticker w wyszukiwaniu: {query}")
            return []
        
        logger.info(f"Wyszukiwanie tickerów dla zapytania: '{query}'")
        
        try:
            params = {
                'q': query,
                'quotes_count': 10,
                'news_count': 0
            }
            
            logger.debug(f"URL: {YAHOO_SEARCH_API_URL}")
            logger.debug(f"Parametry: {params}")
            
            response = requests.get(
                YAHOO_SEARCH_API_URL, 
                params=params, 
                timeout=NETWORK_TIMEOUT_SECONDS
            )
            response.raise_for_status()  # Rzuć wyjątek dla błędnych statusów
            
            logger.debug(f"Status odpowiedzi: {response.status_code}")
            
            data = response.json()
            logger.debug(f"Otrzymano dane: {len(data.get('quotes', []))} wyników")
            
            suggestions = []
            if 'quotes' in data:
                for quote in data['quotes']:
                    symbol = quote.get('symbol', '')
                    name = quote.get('longname') or quote.get('shortname', '')
                    exchange = quote.get('exchange', '')
                    
                    if symbol:
                        # Format: "AAPL - Apple Inc. (NASDAQ)"
                        display = f"{symbol} - {name}" if name else symbol
                        if exchange:
                            display += f" ({exchange})"
                        suggestions.append((symbol, display))
                        logger.debug(f"  Znaleziono: {symbol} - {name}")
            
            logger.info(f"Wyszukiwanie zakończone: {len(suggestions)} sugestii")
            return suggestions
            
        except requests.exceptions.Timeout:
            logger.error(f"Timeout wyszukiwania tickerów dla: {query}")
            return []
        except requests.exceptions.RequestException as e:
            logger.error(f"Błąd wyszukiwania tickerów: {type(e).__name__} - {str(e)}")
            logger.exception("Szczegóły błędu:")
            return []
        except Exception as e:
            logger.error(f"Nieoczekiwany błąd wyszukiwania: {type(e).__name__} - {str(e)}")
            logger.exception("Szczegóły błędu:")
            return []
    
    def update_suggestions(self):
        """Aktualizuje sugestie podczas wpisywania"""
        query = self.ticker_input.text().strip().upper()
        
        if len(query) < 1:
            return
        
        # Wyszukaj tickery
        suggestions = self.search_tickers(query)
        
        # Aktualizuj model autocomplete
        display_list = [display for _, display in suggestions]
        self.suggestions_map = {display: symbol for symbol, display in suggestions}
        
        self.completer_model.setStringList(display_list)
    
    def on_ticker_selected(self, text):
        """Wywoływane gdy użytkownik wybierze ticker z listy"""
        # Znajdź oryginalny symbol
        if text in self.suggestions_map:
            symbol = self.suggestions_map[text]
            self.ticker_input.setText(symbol)
            self.ticker_input.setCursorPosition(len(symbol))
    
    def init_ui(self):
        self.setWindowTitle(f'Dodaj pozycję - {self.currency}')
        self.setMinimumWidth(500)
        
        layout = QFormLayout()
        
        # Data zakupu
        self.date_input = QDateEdit()
        self.date_input.setDate(QDate.currentDate())
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat('yyyy-MM-dd')
        layout.addRow('Data zakupu:', self.date_input)
        
        # Ticker input z autocomplete
        ticker_layout = QVBoxLayout()
        
        self.ticker_input = QLineEdit()
        self.ticker_input.setPlaceholderText('Zacznij wpisywać... (np. AAPL, PKO)')
        
        # Setup autocomplete
        self.completer = QCompleter()
        self.completer_model = QStringListModel()
        self.completer.setModel(self.completer_model)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchContains)
        self.ticker_input.setCompleter(self.completer)
        
        # Mapa sugestii (display text -> symbol)
        self.suggestions_map = {}
        
        # Timer dla opóźnionego wyszukiwania (żeby nie wysyłać zapytania przy każdej literze)
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.update_suggestions)
        
        # Połącz zmianę tekstu z timerem
        self.ticker_input.textChanged.connect(lambda: self.search_timer.start(SEARCH_DEBOUNCE_MS))
        
        # Połącz wybór z autocomplete
        self.completer.activated.connect(self.on_ticker_selected)
        
        ticker_layout.addWidget(self.ticker_input)
        
        hint_label = QLabel('💡 USA: AAPL, MSFT | GPW: PKO.WA, CDR.WA')
        hint_label.setStyleSheet('color: gray; font-size: 10px;')
        ticker_layout.addWidget(hint_label)
        
        layout.addRow('Ticker:', ticker_layout)
        
        self.buy_price_input = QLineEdit()
        self.buy_price_input.setPlaceholderText('150.50')
        layout.addRow('Cena zakupu:', self.buy_price_input)
        
        # Kurs USD - tylko dla waluty PLN (gdy kupujesz USD płacąc w PLN)
        if self.currency == 'PLN':
            self.usd_rate_input = QLineEdit()
            self.usd_rate_input.setPlaceholderText('4.00')
            layout.addRow('Kurs USD/PLN (zakup):', self.usd_rate_input)
            
            # Kurs EUR - tylko dla waluty PLN (gdy kupujesz EUR płacąc w PLN)
            self.eur_rate_input = QLineEdit()
            self.eur_rate_input.setPlaceholderText('4.30')
            layout.addRow('Kurs EUR/PLN (zakup):', self.eur_rate_input)
        
        self.quantity_input = QLineEdit()
        self.quantity_input.setPlaceholderText('10')
        layout.addRow('Wolumen:', self.quantity_input)
        
        # Dywidenda
        self.dividend_input = QLineEdit()
        self.dividend_input.setPlaceholderText('0')
        layout.addRow(f'Dywidenda ({self.currency}):', self.dividend_input)
        
        # Rodzaj instrumentu
        self.instrument_type_combo = QComboBox()
        self.instrument_type_combo.addItems(['Akcje', 'CFD'])
        layout.addRow('Rodzaj instrumentu:', self.instrument_type_combo)
        
        # Dźwignia - tylko dla CFD
        self.leverage_input = QLineEdit()
        self.leverage_input.setPlaceholderText('np. 20')
        self.leverage_input.setEnabled(False)
        layout.addRow('Dźwignia:', self.leverage_input)
        
        # Kierunek - tylko dla CFD
        self.direction_combo = QComboBox()
        self.direction_combo.addItems(['Long (na wzrost)', 'Short (na spadek)'])
        self.direction_combo.setEnabled(False)
        layout.addRow('Kierunek:', self.direction_combo)
        
        # SWAP - tylko dla CFD
        self.swap_input = QLineEdit()
        self.swap_input.setPlaceholderText('Dzienny koszt SWAP (np. 0.50)')
        self.swap_input.setEnabled(False)
        layout.addRow('SWAP (dzienny koszt):', self.swap_input)
        
        # Podłącz sygnał PO utworzeniu wszystkich pól
        self.instrument_type_combo.currentTextChanged.connect(self.on_instrument_type_changed)
        
        # Pole na procent zysku (zamiast bezpośredniej ceny alertu)
        self.profit_percent_input = QLineEdit()
        self.profit_percent_input.setPlaceholderText('20 (dla +20%)')
        self.profit_percent_input.textChanged.connect(self.update_alert_preview)
        layout.addRow('Zakładany zysk (%):', self.profit_percent_input)
        
        # Podgląd obliczonej ceny alertu
        self.alert_preview_label = QLabel('Cel cenowy: -')
        self.alert_preview_label.setStyleSheet('color: #10b981; font-weight: bold;')
        layout.addRow('', self.alert_preview_label)
        
        # LUB bezpośrednia cena (dla zaawansowanych)
        self.alert_price_input = QLineEdit()
        self.alert_price_input.setPlaceholderText('200 (lub wpisz procent powyżej)')
        self.alert_price_input.textChanged.connect(self.update_from_direct_price)
        layout.addRow('LUB bezpośrednia cena:', self.alert_price_input)
        
        # Przyciski
        buttons_layout = QHBoxLayout()
        
        add_button = QPushButton('Dodaj')
        add_button.clicked.connect(self.validate_and_accept)
        add_button.setStyleSheet('background-color: #3b82f6; color: white; padding: 8px;')
        
        cancel_button = QPushButton('Anuluj')
        cancel_button.clicked.connect(self.reject)
        cancel_button.setStyleSheet('background-color: #6b7280; color: white; padding: 8px;')
        
        buttons_layout.addWidget(cancel_button)
        buttons_layout.addWidget(add_button)
        
        layout.addRow(buttons_layout)
        
        self.setLayout(layout)
        
        # Jeśli ticker został podany, automatycznie go wpisz
        if self.prefill_ticker:
            self.ticker_input.setText(self.prefill_ticker)
            self.ticker_input.setFocus()
            # Zablokuj edycję tickera (użytkownik przyszedł z watchlisty)
            self.ticker_input.setEnabled(False)
        
        # Jeśli przekazano prefill_data, wypełnij wszystkie pola
        if self.prefill_data:
            if 'buy_date' in self.prefill_data:
                buy_date = QDate.fromString(self.prefill_data['buy_date'], 'yyyy-MM-dd')
                self.date_input.setDate(buy_date)
            
            if 'ticker' in self.prefill_data:
                self.ticker_input.setText(self.prefill_data['ticker'])
                self.ticker_input.setFocus()
                # Nie blokuj edycji - użytkownik musi poprawić ticker
            
            if 'buy_price' in self.prefill_data:
                self.buy_price_input.setText(str(self.prefill_data['buy_price']))
            
            if self.currency == 'PLN':
                if 'usd_rate' in self.prefill_data and self.prefill_data['usd_rate']:
                    self.usd_rate_input.setText(str(self.prefill_data['usd_rate']))
                if 'eur_rate' in self.prefill_data and self.prefill_data['eur_rate']:
                    self.eur_rate_input.setText(str(self.prefill_data['eur_rate']))
            
            if 'quantity' in self.prefill_data:
                self.quantity_input.setText(str(self.prefill_data['quantity']))
            
            if 'dividend' in self.prefill_data and self.prefill_data['dividend']:
                self.dividend_input.setText(str(self.prefill_data['dividend']))
            
            if 'instrument_type' in self.prefill_data:
                index = self.instrument_type_combo.findText(self.prefill_data['instrument_type'])
                if index >= 0:
                    self.instrument_type_combo.setCurrentIndex(index)
            
            if 'leverage' in self.prefill_data and self.prefill_data['leverage']:
                self.leverage_input.setText(str(self.prefill_data['leverage']))
            
            if 'direction' in self.prefill_data:
                if self.prefill_data['direction'] == 'Short':
                    self.direction_combo.setCurrentIndex(1)
                else:
                    self.direction_combo.setCurrentIndex(0)
            
            if 'swap_daily' in self.prefill_data and self.prefill_data['swap_daily']:
                self.swap_input.setText(str(self.prefill_data['swap_daily']))
            
            # Alert price lub profit percent
            if 'alert_price' in self.prefill_data and self.prefill_data['alert_price']:
                self.alert_price_input.setText(str(self.prefill_data['alert_price']))
            elif 'profit_percent' in self.prefill_data and self.prefill_data['profit_percent']:
                self.profit_percent_input.setText(str(self.prefill_data['profit_percent']))
    
    def update_alert_preview(self):
        """Aktualizuje podgląd ceny alertu na podstawie procentu"""
        try:
            buy_price = float(self.buy_price_input.text())
            profit_percent = float(self.profit_percent_input.text())
            
            if buy_price > 0 and profit_percent > 0:
                alert_price = buy_price * (1 + profit_percent / 100)
                self.alert_preview_label.setText(f'Cel cenowy: {alert_price:.2f} ({self.currency})')
                # Wyczyść bezpośrednią cenę jeśli wpisujemy procent
                self.alert_price_input.blockSignals(True)
                self.alert_price_input.clear()
                self.alert_price_input.blockSignals(False)
            else:
                self.alert_preview_label.setText('Cel cenowy: -')
        except ValueError:
            self.alert_preview_label.setText('Cel cenowy: -')
    
    def update_from_direct_price(self):
        """Czyści procent gdy wpisujemy bezpośrednią cenę"""
        if self.alert_price_input.text().strip():
            self.profit_percent_input.blockSignals(True)
            self.profit_percent_input.clear()
            self.profit_percent_input.blockSignals(False)
            self.alert_preview_label.setText('Użyto bezpośredniej ceny')
    
    def on_instrument_type_changed(self, instrument_type):
        """Włącza/wyłącza pole dźwigni, kierunku i SWAP w zależności od typu instrumentu"""
        if instrument_type == 'CFD':
            self.leverage_input.setEnabled(True)
            self.direction_combo.setEnabled(True)
            self.swap_input.setEnabled(True)
        else:
            self.leverage_input.setEnabled(False)
            self.leverage_input.clear()
            self.direction_combo.setEnabled(False)
            self.direction_combo.setCurrentIndex(0)
            self.swap_input.setEnabled(False)
            self.swap_input.clear()
    
    def validate_and_accept(self):
        try:
            # Sanityzacja i walidacja tickera
            ticker = sanitize_ticker(self.ticker_input.text())
            
            # Konwersja i walidacja wartości
            buy_price = safe_float_convert(self.buy_price_input.text(), "cena zakupu")
            quantity = safe_float_convert(self.quantity_input.text(), "ilość")
            buy_date = self.date_input.date().toString('yyyy-MM-dd')
            
            # Kurs USD - tylko dla waluty PLN (gdy kupujesz USD płacąc w PLN), opcjonalny
            usd_rate = None
            if self.currency == 'PLN' and hasattr(self, 'usd_rate_input'):
                usd_rate_text = self.usd_rate_input.text().strip()
                if usd_rate_text:
                    try:
                        usd_rate = safe_float_convert(usd_rate_text, "kurs USD")
                    except ValueError:
                        usd_rate = None
            
            # Kurs EUR - tylko dla waluty PLN (gdy kupujesz EUR płacąc w PLN), opcjonalny
            eur_rate = None
            if self.currency == 'PLN' and hasattr(self, 'eur_rate_input'):
                eur_rate_text = self.eur_rate_input.text().strip()
                if eur_rate_text:
                    try:
                        eur_rate = safe_float_convert(eur_rate_text, "kurs EUR")
                    except ValueError:
                        eur_rate = None
            
            # Dywidenda (opcjonalna)
            dividend = None
            if hasattr(self, 'dividend_input'):
                dividend_text = self.dividend_input.text().strip()
                if dividend_text:
                    try:
                        dividend = float(dividend_text)
                        if dividend < 0:
                            raise ValueError("Dywidenda musi być >= 0")
                    except ValueError as e:
                        raise ValueError(f"Nieprawidłowa dywidenda: {dividend_text}")
            
            # Rodzaj instrumentu
            instrument_type = self.instrument_type_combo.currentText()
            
            # Dźwignia i kierunek - tylko dla CFD
            leverage = None
            direction = 'Long'
            swap_daily = None
            if instrument_type == 'CFD':
                leverage_text = self.leverage_input.text().strip()
                if leverage_text:
                    try:
                        leverage = safe_float_convert(leverage_text, "dźwignia")
                    except ValueError:
                        raise ValueError("Dla CFD musisz podać dźwignię (np. 20 dla 1:20)")
                else:
                    raise ValueError("Dla CFD musisz podać dźwignię")
                
                # Pobierz kierunek
                direction_text = self.direction_combo.currentText()
                direction = 'Short' if 'Short' in direction_text else 'Long'
                
                # Pobierz SWAP (opcjonalne)
                swap_text = self.swap_input.text().strip()
                if swap_text:
                    try:
                        swap_daily = float(swap_text)
                        if swap_daily < 0:
                            raise ValueError("SWAP dzienny musi być >= 0")
                    except ValueError:
                        raise ValueError("SWAP dzienny musi być liczbą >= 0")
            
            # Oblicz alert_price z procentu lub użyj bezpośredniej ceny
            alert_price = None
            profit_percent = None
            
            # Priorytet: bezpośrednia cena
            alert_text = self.alert_price_input.text().strip()
            if alert_text:
                alert_price = safe_float_convert(alert_text, "cena alertu")
            # Jeśli nie ma bezpośredniej, oblicz z procentu
            elif self.profit_percent_input.text().strip():
                profit_percent = float(self.profit_percent_input.text())
                if profit_percent > 0:
                    alert_price = buy_price * (1 + profit_percent / 100)
            
            self.position_data = {
                'ticker': ticker,
                'buy_price': buy_price,
                'quantity': quantity,
                'usd_rate': usd_rate,
                'eur_rate': eur_rate,
                'alert_price': alert_price,
                'profit_percent': profit_percent,
                'buy_date': buy_date,
                'instrument_type': instrument_type,
                'leverage': leverage,
                'direction': direction,
                'swap_daily': swap_daily,
                'dividend': dividend
            }
            
            self.accept()
            
        except ValueError as e:
            logger.error(f"Błąd walidacji danych: {str(e)}")
            logger.exception("Szczegóły błędu:")
            QMessageBox.warning(self, 'Błąd', f'Błąd walidacji:\n{str(e)}')


class EditPositionDialog(QDialog):
    def __init__(self, position, currency, parent=None):
        super().__init__(parent)
        self.position = position
        self.currency = currency
        self.position_data = None
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle(f'Edytuj pozycję - {self.position["ticker"]}')
        self.setMinimumWidth(500)
        
        layout = QFormLayout()
        
        # Data zakupu
        self.date_input = QDateEdit()
        buy_date = QDate.fromString(self.position['buy_date'], 'yyyy-MM-dd')
        self.date_input.setDate(buy_date)
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat('yyyy-MM-dd')
        layout.addRow('Data zakupu:', self.date_input)
        
        # Ticker (tylko do odczytu - pokazujemy, ale nie edytujemy)
        ticker_label = QLabel(self.position['ticker'])
        ticker_label.setStyleSheet('font-weight: bold; color: #3b82f6;')
        layout.addRow('Ticker:', ticker_label)
        
        self.buy_price_input = QLineEdit()
        self.buy_price_input.setText(str(self.position['buy_price']))
        self.buy_price_input.setPlaceholderText('150.50')
        layout.addRow('Cena zakupu:', self.buy_price_input)
        
        # Kurs USD - tylko dla waluty PLN (gdy kupujesz USD płacąc w PLN)
        if self.currency == 'PLN':
            self.usd_rate_input = QLineEdit()
            if self.position.get('usd_rate'):
                self.usd_rate_input.setText(str(self.position['usd_rate']))
            self.usd_rate_input.setPlaceholderText('4.00')
            layout.addRow('Kurs USD/PLN (zakup):', self.usd_rate_input)
            
            # Kurs EUR - tylko dla waluty PLN (gdy kupujesz EUR płacąc w PLN)
            self.eur_rate_input = QLineEdit()
            if self.position.get('eur_rate'):
                self.eur_rate_input.setText(str(self.position['eur_rate']))
            self.eur_rate_input.setPlaceholderText('4.30')
            layout.addRow('Kurs EUR/PLN (zakup):', self.eur_rate_input)
        
        self.quantity_input = QLineEdit()
        self.quantity_input.setText(str(self.position['quantity']))
        self.quantity_input.setPlaceholderText('10')
        layout.addRow('Wolumen:', self.quantity_input)
        
        # Dywidenda
        self.dividend_input = QLineEdit()
        if self.position.get('dividend'):
            self.dividend_input.setText(str(self.position['dividend']))
        self.dividend_input.setPlaceholderText('0')
        layout.addRow(f'Dywidenda ({self.currency}):', self.dividend_input)
        
        # Rodzaj instrumentu
        self.instrument_type_combo = QComboBox()
        self.instrument_type_combo.addItems(['Akcje', 'CFD'])
        current_type = self.position.get('instrument_type', 'Akcje')
        layout.addRow('Rodzaj instrumentu:', self.instrument_type_combo)
        
        # Dźwignia - tylko dla CFD
        self.leverage_input = QLineEdit()
        if self.position.get('leverage'):
            self.leverage_input.setText(str(self.position['leverage']))
        self.leverage_input.setPlaceholderText('np. 20')
        self.leverage_input.setEnabled(current_type == 'CFD')
        layout.addRow('Dźwignia:', self.leverage_input)
        
        # Kierunek - tylko dla CFD
        self.direction_combo = QComboBox()
        self.direction_combo.addItems(['Long (na wzrost)', 'Short (na spadek)'])
        current_direction = self.position.get('direction', 'Long')
        if current_direction == 'Short':
            self.direction_combo.setCurrentIndex(1)
        self.direction_combo.setEnabled(current_type == 'CFD')
        layout.addRow('Kierunek:', self.direction_combo)
        
        # SWAP - tylko dla CFD
        self.swap_input = QLineEdit()
        if self.position.get('swap_daily'):
            self.swap_input.setText(str(self.position['swap_daily']))
        self.swap_input.setPlaceholderText('Dzienny koszt SWAP (np. 0.50)')
        self.swap_input.setEnabled(current_type == 'CFD')
        layout.addRow('SWAP (dzienny koszt):', self.swap_input)
        
        # Ustaw wartość i podłącz sygnał PO utworzeniu wszystkich pól
        self.instrument_type_combo.setCurrentText(current_type)
        self.instrument_type_combo.currentTextChanged.connect(self.on_instrument_type_changed)
        
        # Pole na procent zysku (zamiast bezpośredniej ceny alertu)
        self.profit_percent_input = QLineEdit()
        # Oblicz procent z istniejącej ceny alertu jeśli istnieje
        if self.position.get('alert_price') and self.position['buy_price']:
            profit_percent = ((self.position['alert_price'] - self.position['buy_price']) / self.position['buy_price']) * 100
            self.profit_percent_input.setText(f"{profit_percent:.1f}")
        self.profit_percent_input.setPlaceholderText('20 (dla +20%)')
        self.profit_percent_input.textChanged.connect(self.update_alert_preview)
        layout.addRow('Zakładany zysk (%):', self.profit_percent_input)
        
        # Podgląd obliczonej ceny alertu
        self.alert_preview_label = QLabel('Cel cenowy: -')
        if self.position.get('alert_price'):
            self.alert_preview_label.setText(f'Cel cenowy: {self.position["alert_price"]:.2f} ({self.currency})')
        self.alert_preview_label.setStyleSheet('color: #10b981; font-weight: bold;')
        layout.addRow('', self.alert_preview_label)
        
        # LUB bezpośrednia cena (dla zaawansowanych)
        self.alert_price_input = QLineEdit()
        if self.position.get('alert_price'):
            self.alert_price_input.setText(str(self.position['alert_price']))
        self.alert_price_input.setPlaceholderText('200 (lub wpisz procent powyżej)')
        self.alert_price_input.textChanged.connect(self.update_from_direct_price)
        layout.addRow('LUB bezpośrednia cena:', self.alert_price_input)
        
        # Przyciski
        buttons_layout = QHBoxLayout()
        
        delete_button = QPushButton('Usuń')
        delete_button.clicked.connect(self.delete_position)
        delete_button.setStyleSheet('background-color: #ef4444; color: white; padding: 8px; font-weight: bold;')
        
        cancel_button = QPushButton('Anuluj')
        cancel_button.clicked.connect(self.reject)
        cancel_button.setStyleSheet('background-color: #6b7280; color: white; padding: 8px;')
        
        save_button = QPushButton('Zapisz')
        save_button.clicked.connect(self.validate_and_accept)
        save_button.setStyleSheet('background-color: #10b981; color: white; padding: 8px; font-weight: bold;')
        
        buttons_layout.addWidget(delete_button)
        buttons_layout.addWidget(cancel_button)
        buttons_layout.addWidget(save_button)
        
        layout.addRow(buttons_layout)
        
        self.setLayout(layout)
    
    def update_alert_preview(self):
        """Aktualizuje podgląd ceny alertu na podstawie procentu"""
        try:
            buy_price = float(self.buy_price_input.text())
            profit_percent = float(self.profit_percent_input.text())
            
            if buy_price > 0 and profit_percent > 0:
                alert_price = buy_price * (1 + profit_percent / 100)
                self.alert_preview_label.setText(f'Cel cenowy: {alert_price:.2f} ({self.currency})')
                # Wyczyść bezpośrednią cenę jeśli wpisujemy procent
                self.alert_price_input.blockSignals(True)
                self.alert_price_input.clear()
                self.alert_price_input.blockSignals(False)
            else:
                self.alert_preview_label.setText('Cel cenowy: -')
        except ValueError:
            self.alert_preview_label.setText('Cel cenowy: -')
    
    def update_from_direct_price(self):
        """Czyści procent gdy wpisujemy bezpośrednią cenę"""
        if self.alert_price_input.text().strip():
            self.profit_percent_input.blockSignals(True)
            self.profit_percent_input.clear()
            self.profit_percent_input.blockSignals(False)
            self.alert_preview_label.setText('Użyto bezpośredniej ceny')
    
    def on_instrument_type_changed(self, instrument_type):
        """Włącza/wyłącza pole dźwigni i kierunku w zależności od typu instrumentu"""
        if instrument_type == 'CFD':
            self.leverage_input.setEnabled(True)
            self.direction_combo.setEnabled(True)
            self.swap_input.setEnabled(True)
        else:
            self.leverage_input.setEnabled(False)
            self.leverage_input.clear()
            self.direction_combo.setEnabled(False)
            self.direction_combo.setCurrentIndex(0)
            self.swap_input.setEnabled(False)
            self.swap_input.clear()
    
    def delete_position(self):
        """Usuwa pozycję po potwierdzeniu"""
        reply = QMessageBox.question(
            self, 
            'Potwierdź usunięcie',
            f'Czy na pewno chcesz usunąć pozycję {self.position["ticker"]}?\n\nTej operacji nie można cofnąć.',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Ustaw flagę usunięcia i zamknij dialog
            self.position_data = {'delete': True}
            self.accept()
    
    def validate_and_accept(self):
        try:
            buy_price = safe_float_convert(self.buy_price_input.text(), "cena zakupu")
            quantity = safe_float_convert(self.quantity_input.text(), "ilość")
            buy_date = self.date_input.date().toString('yyyy-MM-dd')
            
            # Kurs USD - tylko dla waluty PLN (gdy kupujesz USD płacąc w PLN), opcjonalny
            usd_rate = None
            if self.currency == 'PLN' and hasattr(self, 'usd_rate_input'):
                usd_rate_text = self.usd_rate_input.text().strip()
                if usd_rate_text:
                    try:
                        usd_rate = safe_float_convert(usd_rate_text, "kurs USD")
                    except ValueError:
                        usd_rate = None
            
            # Kurs EUR - tylko dla waluty PLN (gdy kupujesz EUR płacąc w PLN), opcjonalny
            eur_rate = None
            if self.currency == 'PLN' and hasattr(self, 'eur_rate_input'):
                eur_rate_text = self.eur_rate_input.text().strip()
                if eur_rate_text:
                    try:
                        eur_rate = safe_float_convert(eur_rate_text, "kurs EUR")
                    except ValueError:
                        eur_rate = None
            
            # Dywidenda (opcjonalna)
            dividend = None
            if hasattr(self, 'dividend_input'):
                dividend_text = self.dividend_input.text().strip()
                if dividend_text:
                    try:
                        dividend = float(dividend_text)
                        if dividend < 0:
                            raise ValueError("Dywidenda musi być >= 0")
                    except ValueError as e:
                        raise ValueError(f"Nieprawidłowa dywidenda: {dividend_text}")
            
            # Rodzaj instrumentu
            instrument_type = self.instrument_type_combo.currentText()
            
            # Dźwignia, kierunek i SWAP - tylko dla CFD
            leverage = None
            direction = 'Long'
            swap_daily = None  # Zdefiniuj na początku
            
            if instrument_type == 'CFD':
                leverage_text = self.leverage_input.text().strip()
                if leverage_text:
                    try:
                        leverage = safe_float_convert(leverage_text, "dźwignia")
                    except ValueError:
                        raise ValueError("Dla CFD musisz podać dźwignię (np. 20 dla 1:20)")
                else:
                    raise ValueError("Dla CFD musisz podać dźwignię")
                
                # Pobierz kierunek
                direction_text = self.direction_combo.currentText()
                direction = 'Short' if 'Short' in direction_text else 'Long'
                
                # Pobierz SWAP (opcjonalne)
                swap_text = self.swap_input.text().strip()
                if swap_text:
                    try:
                        swap_daily = float(swap_text)
                        if swap_daily < 0:
                            raise ValueError("SWAP dzienny musi być >= 0")
                    except ValueError:
                        raise ValueError("SWAP dzienny musi być liczbą >= 0")
            
            # Oblicz alert_price z procentu lub użyj bezpośredniej ceny
            alert_price = None
            
            # Priorytet: bezpośrednia cena
            alert_text = self.alert_price_input.text().strip()
            if alert_text:
                alert_price = safe_float_convert(alert_text, "cena alertu")
            # Jeśli nie ma bezpośredniej, oblicz z procentu
            elif self.profit_percent_input.text().strip():
                profit_percent = float(self.profit_percent_input.text())
                if profit_percent > 0:
                    alert_price = buy_price * (1 + profit_percent / 100)
            
            self.position_data = {
                'buy_price': buy_price,
                'quantity': quantity,
                'usd_rate': usd_rate,
                'eur_rate': eur_rate,
                'alert_price': alert_price,
                'buy_date': buy_date,
                'instrument_type': instrument_type,
                'leverage': leverage,
                'direction': direction,
                'swap_daily': swap_daily,
                'dividend': dividend
            }
            
            self.accept()
            
        except ValueError as e:
            logger.error(f"Błąd walidacji danych: {str(e)}")
            logger.exception("Szczegóły błędu:")
            QMessageBox.warning(self, 'Błąd', f'Błąd walidacji:\n{str(e)}')


class ClosePositionDialog(QDialog):
    def __init__(self, position, current_price, currency, parent=None):
        super().__init__(parent)
        self.position = position
        self.current_price = current_price
        self.currency = currency
        self.close_data = None
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle(f'Zamknij pozycję - {self.position["ticker"]}')
        self.setMinimumWidth(400)
        
        layout = QFormLayout()
        
        # Data sprzedaży
        self.sell_date_input = QDateEdit()
        self.sell_date_input.setDate(QDate.currentDate())
        self.sell_date_input.setCalendarPopup(True)
        self.sell_date_input.setDisplayFormat('yyyy-MM-dd')
        layout.addRow('Data sprzedaży:', self.sell_date_input)
        
        # Cena sprzedaży
        self.sell_price_input = QLineEdit()
        self.sell_price_input.setText(f"{self.current_price:.2f}")
        self.sell_price_input.setPlaceholderText('Cena sprzedaży')
        layout.addRow('Cena sprzedaży:', self.sell_price_input)
        
        # SWAP - tylko dla CFD
        instrument_type = self.position.get('instrument_type', 'Akcje')
        if instrument_type == 'CFD':
            self.swap_input = QLineEdit()
            self.swap_input.setPlaceholderText('0.00')
            self.swap_input.setText('0.00')
            layout.addRow('Koszt SWAP (całkowity):', self.swap_input)
        
        # Dywidenda - dla wszystkich typów
        self.dividend_input = QLineEdit()
        # Sprawdź czy pozycja ma już zapisaną dywidendę
        if self.position.get('dividend'):
            self.dividend_input.setText(str(self.position['dividend']))
        else:
            self.dividend_input.setText('0.00')
        self.dividend_input.setPlaceholderText('0.00')
        layout.addRow('💰 Dywidenda (wypłacona):', self.dividend_input)
        
        # Kurs USD - tylko dla waluty PLN (gdy sprzedajesz USD za PLN)
        if self.currency == 'PLN':
            self.usd_rate_input = QLineEdit()
            # Jeśli była zapisana stawka kupna, użyj jej jako domyślnej
            if self.position.get('usd_rate'):
                self.usd_rate_input.setText(f"{self.position['usd_rate']:.2f}")
            self.usd_rate_input.setPlaceholderText('4.00')
            layout.addRow('Kurs USD/PLN (sprzedaż):', self.usd_rate_input)
        
        # Informacje o pozycji
        info_label = QLabel(
            f"Ticker: {self.position['ticker']}\n"
            f"Cena zakupu: {self.position['buy_price']:.2f}\n"
            f"Ilość: {self.position['quantity']:.2f}"
        )
        info_label.setStyleSheet('color: gray; padding: 10px;')
        layout.addRow('', info_label)
        
        # Przyciski
        buttons_layout = QHBoxLayout()
        
        save_button = QPushButton('Zapisz')
        save_button.clicked.connect(self.validate_and_accept)
        save_button.setStyleSheet('background-color: #10b981; color: white; padding: 8px; font-weight: bold;')
        
        cancel_button = QPushButton('Anuluj')
        cancel_button.clicked.connect(self.reject)
        cancel_button.setStyleSheet('background-color: #6b7280; color: white; padding: 8px;')
        
        buttons_layout.addWidget(cancel_button)
        buttons_layout.addWidget(save_button)
        
        layout.addRow(buttons_layout)
        
        self.setLayout(layout)
    
    def validate_and_accept(self):
        try:
            sell_price = safe_float_convert(self.sell_price_input.text(), "cena sprzedaży")
            sell_date = self.sell_date_input.date().toString('yyyy-MM-dd')
            
            # SWAP - tylko dla CFD
            swap_cost = 0.0
            instrument_type = self.position.get('instrument_type', 'Akcje')
            if instrument_type == 'CFD' and hasattr(self, 'swap_input'):
                swap_text = self.swap_input.text().strip()
                if swap_text:
                    try:
                        swap_cost = float(swap_text)
                        if swap_cost < 0:
                            raise ValueError("Koszt SWAP nie może być ujemny")
                    except ValueError as e:
                        raise ValueError(f"Nieprawidłowy koszt SWAP: {swap_text}")
            
            # Dywidenda - opcjonalna
            dividend = 0.0
            dividend_text = self.dividend_input.text().strip()
            if dividend_text:
                try:
                    dividend = float(dividend_text)
                    if dividend < 0:
                        raise ValueError("Dywidenda nie może być ujemna")
                except ValueError:
                    raise ValueError("Dywidenda musi być liczbą >= 0")
            
            # Kurs USD - tylko dla waluty PLN (gdy sprzedajesz USD za PLN), opcjonalny
            usd_rate = None
            if self.currency == 'PLN' and hasattr(self, 'usd_rate_input'):
                usd_rate_text = self.usd_rate_input.text().strip()
                if usd_rate_text:
                    try:
                        usd_rate = safe_float_convert(usd_rate_text, "kurs USD")
                    except ValueError:
                        usd_rate = None
            
            self.close_data = {
                'sell_price': sell_price,
                'sell_date': sell_date,
                'usd_rate': usd_rate,
                'swap_cost': swap_cost,
                'dividend': dividend
            }
            
            self.accept()
            
        except ValueError as e:
            logger.error(f"Błąd walidacji danych zamknięcia pozycji: {str(e)}")
            logger.exception("Szczegóły błędu:")
            QMessageBox.warning(self, 'Błąd', f'Błąd walidacji:\n{str(e)}')


class EditHistoryDialog(QDialog):
    def __init__(self, history_item, currency, parent=None):
        super().__init__(parent)
        self.history_item = history_item
        self.currency = currency
        self.history_data = None
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle(f'Edytuj transakcję - {self.history_item["ticker"]}')
        self.setMinimumWidth(500)
        
        layout = QFormLayout()
        
        # Ticker (tylko do odczytu)
        ticker_label = QLabel(self.history_item['ticker'])
        ticker_label.setStyleSheet('font-weight: bold; color: #3b82f6;')
        layout.addRow('Ticker:', ticker_label)
        
        # Data zakupu
        self.buy_date_input = QDateEdit()
        buy_date = QDate.fromString(self.history_item['buy_date'], 'yyyy-MM-dd')
        self.buy_date_input.setDate(buy_date)
        self.buy_date_input.setCalendarPopup(True)
        self.buy_date_input.setDisplayFormat('yyyy-MM-dd')
        layout.addRow('Data zakupu:', self.buy_date_input)
        
        # Cena zakupu
        self.buy_price_input = QLineEdit()
        self.buy_price_input.setText(str(self.history_item['buy_price']))
        layout.addRow('Cena zakupu:', self.buy_price_input)
        
        # Data sprzedaży
        self.sell_date_input = QDateEdit()
        sell_date = QDate.fromString(self.history_item['sell_date'], 'yyyy-MM-dd')
        self.sell_date_input.setDate(sell_date)
        self.sell_date_input.setCalendarPopup(True)
        self.sell_date_input.setDisplayFormat('yyyy-MM-dd')
        layout.addRow('Data sprzedaży:', self.sell_date_input)
        
        # Cena sprzedaży
        self.sell_price_input = QLineEdit()
        self.sell_price_input.setText(str(self.history_item['sell_price']))
        layout.addRow('Cena sprzedaży:', self.sell_price_input)
        
        # Ilość
        self.quantity_input = QLineEdit()
        self.quantity_input.setText(str(self.history_item['quantity']))
        layout.addRow('Wolumen:', self.quantity_input)
        
        # Rodzaj instrumentu
        self.instrument_type_combo = QComboBox()
        self.instrument_type_combo.addItems(['Akcje', 'CFD'])
        current_type = self.history_item.get('instrument_type', 'Akcje')
        layout.addRow('Rodzaj instrumentu:', self.instrument_type_combo)
        
        # Dźwignia - tylko dla CFD
        self.leverage_input = QLineEdit()
        if self.history_item.get('leverage'):
            self.leverage_input.setText(str(self.history_item['leverage']))
        self.leverage_input.setPlaceholderText('20 (dla 1:20)')
        self.leverage_input.setEnabled(current_type == 'CFD')
        layout.addRow('Dźwignia:', self.leverage_input)
        
        # Kierunek - tylko dla CFD
        self.direction_combo = QComboBox()
        self.direction_combo.addItems(['Long (na wzrost)', 'Short (na spadek)'])
        current_direction = self.history_item.get('direction', 'Long')
        if current_direction == 'Short':
            self.direction_combo.setCurrentIndex(1)
        self.direction_combo.setEnabled(current_type == 'CFD')
        layout.addRow('Kierunek:', self.direction_combo)
        
        # SWAP - tylko dla CFD
        self.swap_input = QLineEdit()
        if self.history_item.get('swap_daily'):
            self.swap_input.setText(str(self.history_item['swap_daily']))
        self.swap_input.setPlaceholderText('Dzienny koszt SWAP (np. 0.50)')
        self.swap_input.setEnabled(current_type == 'CFD')
        layout.addRow('SWAP (dzienny koszt):', self.swap_input)
        
        # Ustaw wartość i podłącz sygnał PO utworzeniu wszystkich pól
        self.instrument_type_combo.setCurrentText(current_type)
        self.instrument_type_combo.currentTextChanged.connect(self.on_instrument_type_changed)
        
        # Dywidenda - dla wszystkich typów
        self.dividend_input = QLineEdit()
        if self.history_item.get('dividend'):
            self.dividend_input.setText(str(self.history_item['dividend']))
        self.dividend_input.setPlaceholderText('0.00')
        layout.addRow('💰 Dywidenda:', self.dividend_input)
        
        # Kurs USD - tylko dla waluty PLN (gdy kupujesz/sprzedajesz USD płacąc w PLN)
        if self.currency == 'PLN':
            self.usd_rate_input = QLineEdit()
            if self.history_item.get('usd_rate'):
                self.usd_rate_input.setText(str(self.history_item['usd_rate']))
            self.usd_rate_input.setPlaceholderText('4.00')
            layout.addRow('Kurs USD/PLN:', self.usd_rate_input)
        
        # Przyciski
        buttons_layout = QHBoxLayout()
        
        delete_button = QPushButton('Usuń')
        delete_button.clicked.connect(self.delete_history)
        delete_button.setStyleSheet('background-color: #ef4444; color: white; padding: 8px; font-weight: bold;')
        
        cancel_button = QPushButton('Anuluj')
        cancel_button.clicked.connect(self.reject)
        cancel_button.setStyleSheet('background-color: #6b7280; color: white; padding: 8px;')
        
        save_button = QPushButton('Zapisz')
        save_button.clicked.connect(self.validate_and_accept)
        save_button.setStyleSheet('background-color: #10b981; color: white; padding: 8px; font-weight: bold;')
        
        buttons_layout.addWidget(delete_button)
        buttons_layout.addWidget(cancel_button)
        buttons_layout.addWidget(save_button)
        
        layout.addRow(buttons_layout)
        
        self.setLayout(layout)
    
    def on_instrument_type_changed(self, instrument_type):
        """Włącza/wyłącza pole dźwigni i kierunku w zależności od typu instrumentu"""
        if instrument_type == 'CFD':
            self.leverage_input.setEnabled(True)
            self.direction_combo.setEnabled(True)
            self.swap_input.setEnabled(True)
        else:
            self.leverage_input.setEnabled(False)
            self.leverage_input.clear()
            self.direction_combo.setEnabled(False)
            self.direction_combo.setCurrentIndex(0)
            self.swap_input.setEnabled(False)
            self.swap_input.clear()
    
    def delete_history(self):
        """Usuwa transakcję z historii po potwierdzeniu"""
        reply = QMessageBox.question(
            self, 
            'Potwierdź usunięcie',
            f'Czy na pewno chcesz usunąć transakcję {self.history_item["ticker"]} z historii?\n\nTej operacji nie można cofnąć.',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Ustaw flagę usunięcia i zamknij dialog
            self.history_data = {'delete': True}
            self.accept()
    
    def validate_and_accept(self):
        try:
            buy_price = safe_float_convert(self.buy_price_input.text(), "cena zakupu")
            sell_price = safe_float_convert(self.sell_price_input.text(), "cena sprzedaży")
            quantity = safe_float_convert(self.quantity_input.text(), "ilość")
            buy_date = self.buy_date_input.date().toString('yyyy-MM-dd')
            sell_date = self.sell_date_input.date().toString('yyyy-MM-dd')
            
            # Rodzaj instrumentu
            instrument_type = self.instrument_type_combo.currentText()
            
            # Dźwignia, kierunek i SWAP - tylko dla CFD
            leverage = None
            direction = 'Long'
            swap_daily = None
            
            if instrument_type == 'CFD':
                leverage_text = self.leverage_input.text().strip()
                if leverage_text:
                    try:
                        leverage = safe_float_convert(leverage_text, "dźwignia")
                    except ValueError:
                        raise ValueError("Dla CFD musisz podać dźwignię (np. 20 dla 1:20)")
                else:
                    raise ValueError("Dla CFD musisz podać dźwignię")
                
                # Pobierz kierunek
                direction_text = self.direction_combo.currentText()
                direction = 'Short' if 'Short' in direction_text else 'Long'
                
                # Pobierz SWAP (opcjonalne)
                swap_text = self.swap_input.text().strip()
                if swap_text:
                    try:
                        swap_daily = float(swap_text)
                        if swap_daily < 0:
                            raise ValueError("SWAP dzienny musi być >= 0")
                    except ValueError:
                        raise ValueError("SWAP dzienny musi być liczbą >= 0")
            
            # Oblicz zysk podstawowy (różnica cen * ilość)
            # Dla CFD NIE mnożymy przez leverage, tylko później przez kurs wymiany!
            if direction == 'Short':
                # Dla short zarabiamy gdy cena spada
                profit = (buy_price - sell_price) * quantity
            else:
                # Dla long zarabiamy gdy cena rośnie
                profit = (sell_price - buy_price) * quantity
            
            # Kurs USD - tylko dla waluty PLN (gdy kupujesz/sprzedajesz USD płacąc w PLN), opcjonalny
            usd_rate = None
            if self.currency == 'PLN' and hasattr(self, 'usd_rate_input'):
                usd_rate_text = self.usd_rate_input.text().strip()
                if usd_rate_text:
                    try:
                        usd_rate = safe_float_convert(usd_rate_text, "kurs USD")
                    except ValueError:
                        usd_rate = None
            
            # Dla PLN z kursem USD - przelicz zysk przez kurs (tu jest mnożenie przez exchange_rate!)
            if self.currency == 'PLN' and usd_rate:
                profit = profit * usd_rate
            
            # Dywidenda - opcjonalna
            dividend = 0.0
            dividend_text = self.dividend_input.text().strip()
            if dividend_text:
                try:
                    dividend = float(dividend_text)
                    if dividend < 0:
                        raise ValueError("Dywidenda nie może być ujemna")
                except ValueError:
                    raise ValueError("Dywidenda musi być liczbą >= 0")
            
            self.history_data = {
                'buy_price': buy_price,
                'sell_price': sell_price,
                'quantity': quantity,
                'profit': profit,
                'buy_date': buy_date,
                'sell_date': sell_date,
                'usd_rate': usd_rate,
                'instrument_type': instrument_type,
                'leverage': leverage if instrument_type == 'CFD' else None,
                'direction': direction,
                'swap_daily': swap_daily,
                'dividend': dividend
            }
            
            self.accept()
            
        except ValueError as e:
            logger.error(f"Błąd walidacji danych historii: {str(e)}")
            logger.exception("Szczegóły błędu:")
            QMessageBox.warning(self, 'Błąd', f'Błąd walidacji:\n{str(e)}')


class AddWatchlistDialog(QDialog):
    def __init__(self, currency, parent=None, prefill_data=None):
        super().__init__(parent)
        self.currency = currency
        self.watchlist_data = None
        self.ticker_suggestions = []
        self.prefill_data = prefill_data  # Dane do wypełnienia formularza
        self.init_ui()
    
    @retry_on_failure(max_attempts=3, delay=1.0, backoff=2.0, 
                      exceptions=(requests.RequestException, requests.Timeout))
    def search_tickers(self, query):
        """Wyszukuje tickery w Yahoo Finance z retry mechanism"""
        if len(query) < 1:
            return []
        
        logger.info(f"Wyszukiwanie tickerów dla zapytania: '{query}'")
        
        try:
            url = f"https://query2.finance.yahoo.com/v1/finance/search"
            params = {
                'q': query,
                'quotes_count': 10,
                'news_count': 0
            }
            
            response = requests.get(url, params=params, timeout=3)
            data = response.json()
            
            suggestions = []
            if 'quotes' in data:
                for quote in data['quotes']:
                    symbol = quote.get('symbol', '')
                    name = quote.get('longname') or quote.get('shortname', '')
                    exchange = quote.get('exchange', '')
                    
                    if symbol:
                        display = f"{symbol} - {name}" if name else symbol
                        if exchange:
                            display += f" ({exchange})"
                        suggestions.append((symbol, display))
            
            return suggestions
            
        except Exception as e:
            logger.error(f"Błąd wyszukiwania tickerów: {type(e).__name__} - {str(e)}")
            return []
    
    def update_suggestions(self):
        """Aktualizuje sugestie podczas wpisywania"""
        query = self.ticker_input.text().strip().upper()
        
        if len(query) < 1:
            return
        
        suggestions = self.search_tickers(query)
        display_list = [display for _, display in suggestions]
        self.suggestions_map = {display: symbol for symbol, display in suggestions}
        self.completer_model.setStringList(display_list)
    
    def on_ticker_selected(self, text):
        """Wywoływane gdy użytkownik wybierze ticker z listy"""
        if text in self.suggestions_map:
            symbol = self.suggestions_map[text]
            self.ticker_input.setText(symbol)
            self.ticker_input.setCursorPosition(len(symbol))
    
    def init_ui(self):
        self.setWindowTitle(f'Dodaj do obserwowanych - {self.currency}')
        self.setMinimumWidth(500)
        
        layout = QFormLayout()
        
        # Ticker input z autocomplete
        ticker_layout = QVBoxLayout()
        
        self.ticker_input = QLineEdit()
        self.ticker_input.setPlaceholderText('Zacznij wpisywać... (np. AAPL, PKO)')
        
        # Setup autocomplete
        self.completer = QCompleter()
        self.completer_model = QStringListModel()
        self.completer.setModel(self.completer_model)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchContains)
        self.ticker_input.setCompleter(self.completer)
        
        self.suggestions_map = {}
        
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.update_suggestions)
        
        self.ticker_input.textChanged.connect(lambda: self.search_timer.start(300))
        self.completer.activated.connect(self.on_ticker_selected)
        
        ticker_layout.addWidget(self.ticker_input)
        
        hint_label = QLabel('💡 USA: AAPL, MSFT | GPW: PKO.WA, CDR.WA')
        hint_label.setStyleSheet('color: gray; font-size: 10px;')
        ticker_layout.addWidget(hint_label)
        
        layout.addRow('Ticker:', ticker_layout)
        
        # Poziomy cenowe
        info_label = QLabel('Wpisz poziomy cenowe, przy których chcesz otrzymać alert:')
        info_label.setStyleSheet('color: #3b82f6; font-weight: bold; padding: 10px 0;')
        layout.addRow('', info_label)
        
        self.hp1_input = QLineEdit()
        self.hp1_input.setPlaceholderText('Poziom 1 (opcjonalnie)')
        layout.addRow('HP1:', self.hp1_input)
        
        self.hp2_input = QLineEdit()
        self.hp2_input.setPlaceholderText('Poziom 2 (opcjonalnie)')
        layout.addRow('HP2:', self.hp2_input)
        
        self.hp3_input = QLineEdit()
        self.hp3_input.setPlaceholderText('Poziom 3 (opcjonalnie)')
        layout.addRow('HP3:', self.hp3_input)
        
        self.hp4_input = QLineEdit()
        self.hp4_input.setPlaceholderText('Poziom 4 (opcjonalnie)')
        layout.addRow('HP4:', self.hp4_input)
        
        # Notatka
        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText('Dodaj notatkę (opcjonalnie)')
        layout.addRow('Notatka:', self.note_input)
        
        # Przyciski
        buttons_layout = QHBoxLayout()
        
        add_button = QPushButton('Dodaj')
        add_button.clicked.connect(self.validate_and_accept)
        add_button.setStyleSheet('background-color: #3b82f6; color: white; padding: 8px;')
        
        cancel_button = QPushButton('Anuluj')
        cancel_button.clicked.connect(self.reject)
        cancel_button.setStyleSheet('background-color: #6b7280; color: white; padding: 8px;')
        
        buttons_layout.addWidget(cancel_button)
        buttons_layout.addWidget(add_button)
        
        layout.addRow(buttons_layout)
        
        self.setLayout(layout)
        
        # Jeśli przekazano prefill_data, wypełnij wszystkie pola
        if self.prefill_data:
            if 'ticker' in self.prefill_data:
                self.ticker_input.setText(self.prefill_data['ticker'])
                self.ticker_input.setFocus()
            
            if 'hp1' in self.prefill_data and self.prefill_data['hp1']:
                self.hp1_input.setText(str(self.prefill_data['hp1']))
            
            if 'hp2' in self.prefill_data and self.prefill_data['hp2']:
                self.hp2_input.setText(str(self.prefill_data['hp2']))
            
            if 'hp3' in self.prefill_data and self.prefill_data['hp3']:
                self.hp3_input.setText(str(self.prefill_data['hp3']))
            
            if 'hp4' in self.prefill_data and self.prefill_data['hp4']:
                self.hp4_input.setText(str(self.prefill_data['hp4']))
            
            if 'note' in self.prefill_data and self.prefill_data['note']:
                self.note_input.setText(self.prefill_data['note'])
    
    def validate_and_accept(self):
        try:
            ticker = sanitize_ticker(self.ticker_input.text())
            
            # Poziomy cenowe - wszystkie opcjonalne
            hp1 = None
            hp2 = None
            hp3 = None
            hp4 = None
            
            if self.hp1_input.text().strip():
                hp1 = safe_float_convert(self.hp1_input.text(), "HP1")
            if self.hp2_input.text().strip():
                hp2 = safe_float_convert(self.hp2_input.text(), "HP2")
            if self.hp3_input.text().strip():
                hp3 = safe_float_convert(self.hp3_input.text(), "HP3")
            if self.hp4_input.text().strip():
                hp4 = safe_float_convert(self.hp4_input.text(), "HP4")
            
            # Notatka (opcjonalna)
            note = self.note_input.text().strip() if self.note_input.text().strip() else None
            
            self.watchlist_data = {
                'ticker': ticker,
                'hp1': hp1,
                'hp2': hp2,
                'hp3': hp3,
                'hp4': hp4,
                'note': note
            }
            
            self.accept()
            
        except ValueError as e:
            logger.error(f"Błąd walidacji danych watchlisty: {str(e)}")
            logger.exception("Szczegóły błędu:")
            QMessageBox.warning(self, 'Błąd', f'Błąd walidacji:\n{str(e)}')


class EditWatchlistDialog(QDialog):
    def __init__(self, watchlist_item, currency, parent=None):
        super().__init__(parent)
        self.watchlist_item = watchlist_item
        self.currency = currency
        self.watchlist_data = None
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle(f'Edytuj obserwowaną - {self.watchlist_item["ticker"]}')
        self.setMinimumWidth(500)
        
        layout = QFormLayout()
        
        # Ticker (tylko do odczytu)
        ticker_label = QLabel(self.watchlist_item['ticker'])
        ticker_label.setStyleSheet('font-weight: bold; color: #3b82f6;')
        layout.addRow('Ticker:', ticker_label)
        
        # Poziomy cenowe
        info_label = QLabel('Edytuj poziomy cenowe alertów:')
        info_label.setStyleSheet('color: #3b82f6; font-weight: bold; padding: 10px 0;')
        layout.addRow('', info_label)
        
        self.hp1_input = QLineEdit()
        if self.watchlist_item.get('hp1'):
            self.hp1_input.setText(str(self.watchlist_item['hp1']))
        self.hp1_input.setPlaceholderText('Poziom 1 (opcjonalnie)')
        layout.addRow('HP1:', self.hp1_input)
        
        self.hp2_input = QLineEdit()
        if self.watchlist_item.get('hp2'):
            self.hp2_input.setText(str(self.watchlist_item['hp2']))
        self.hp2_input.setPlaceholderText('Poziom 2 (opcjonalnie)')
        layout.addRow('HP2:', self.hp2_input)
        
        self.hp3_input = QLineEdit()
        if self.watchlist_item.get('hp3'):
            self.hp3_input.setText(str(self.watchlist_item['hp3']))
        self.hp3_input.setPlaceholderText('Poziom 3 (opcjonalnie)')
        layout.addRow('HP3:', self.hp3_input)
        
        self.hp4_input = QLineEdit()
        if self.watchlist_item.get('hp4'):
            self.hp4_input.setText(str(self.watchlist_item['hp4']))
        self.hp4_input.setPlaceholderText('Poziom 4 (opcjonalnie)')
        layout.addRow('HP4:', self.hp4_input)
        
        # Notatka
        self.note_input = QLineEdit()
        if self.watchlist_item.get('note'):
            self.note_input.setText(self.watchlist_item['note'])
        self.note_input.setPlaceholderText('Dodaj notatkę (opcjonalnie)')
        layout.addRow('Notatka:', self.note_input)
        
        # Przyciski
        buttons_layout = QHBoxLayout()
        
        delete_button = QPushButton('Usuń')
        delete_button.clicked.connect(self.delete_watchlist)
        delete_button.setStyleSheet('background-color: #ef4444; color: white; padding: 8px; font-weight: bold;')
        
        cancel_button = QPushButton('Anuluj')
        cancel_button.clicked.connect(self.reject)
        cancel_button.setStyleSheet('background-color: #6b7280; color: white; padding: 8px;')
        
        save_button = QPushButton('Zapisz')
        save_button.clicked.connect(self.validate_and_accept)
        save_button.setStyleSheet('background-color: #10b981; color: white; padding: 8px; font-weight: bold;')
        
        buttons_layout.addWidget(delete_button)
        buttons_layout.addWidget(cancel_button)
        buttons_layout.addWidget(save_button)
        
        layout.addRow(buttons_layout)
        
        self.setLayout(layout)
    
    def delete_watchlist(self):
        """Usuwa pozycję z obserwowanych po potwierdzeniu"""
        reply = QMessageBox.question(
            self, 
            'Potwierdź usunięcie',
            f'Czy na pewno chcesz usunąć {self.watchlist_item["ticker"]} z obserwowanych?\n\nTej operacji nie można cofnąć.',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Ustaw flagę usunięcia i zamknij dialog
            self.watchlist_data = {'delete': True}
            self.accept()
    
    def validate_and_accept(self):
        try:
            # Poziomy cenowe - wszystkie opcjonalne
            hp1 = None
            hp2 = None
            hp3 = None
            hp4 = None
            
            if self.hp1_input.text().strip():
                hp1 = safe_float_convert(self.hp1_input.text(), "HP1")
            if self.hp2_input.text().strip():
                hp2 = safe_float_convert(self.hp2_input.text(), "HP2")
            if self.hp3_input.text().strip():
                hp3 = safe_float_convert(self.hp3_input.text(), "HP3")
            if self.hp4_input.text().strip():
                hp4 = safe_float_convert(self.hp4_input.text(), "HP4")
            
            # Notatka (opcjonalna)
            note = self.note_input.text().strip() if self.note_input.text().strip() else None
            
            self.watchlist_data = {
                'hp1': hp1,
                'hp2': hp2,
                'hp3': hp3,
                'hp4': hp4,
                'note': note
            }
            
            self.accept()
            
        except ValueError as e:
            logger.error(f"Błąd walidacji danych watchlisty: {str(e)}")
            logger.exception("Szczegóły błędu:")
            QMessageBox.warning(self, 'Błąd', f'Błąd walidacji:\n{str(e)}')


class PlayStrategyDialog(QDialog):
    """Dialog do wprowadzania danych podczas rozgrywania strategii"""
    def __init__(self, strategy, parent=None):
        super().__init__(parent)
        self.strategy = strategy
        self.strategy_data = None
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle(f'Rozegraj strategię - {self.strategy["ticker"]}')
        self.setMinimumWidth(400)
        
        layout = QFormLayout()
        
        # Informacje o strategii
        info_text = f"Ticker: {self.strategy['ticker']}\nStrategia: {self.strategy['strategy_percent']}%"
        info_label = QLabel(info_text)
        info_label.setStyleSheet('color: #3b82f6; font-weight: bold; padding: 10px; background-color: #eff6ff; border-radius: 5px;')
        layout.addRow('', info_label)
        
        # Wybór poziomu zakupu z listy
        self.level_combo = QComboBox()
        levels = self.strategy['levels']
        for level in levels:
            self.level_combo.addItem(
                f"Poziom {level['level']}: {level['price']:.2f}",
                level['price']
            )
        self.level_combo.currentIndexChanged.connect(self.on_level_selected)
        layout.addRow('Wybierz poziom:', self.level_combo)
        
        # Pole na cenę zakupu (automatycznie wypełniane)
        self.buy_price_input = QLineEdit()
        self.buy_price_input.setText(f"{levels[0]['price']:.2f}")
        self.buy_price_input.setPlaceholderText('Cena zakupu')
        layout.addRow('Cena zakupu:', self.buy_price_input)
        
        # Pole na wolumen
        self.quantity_input = QLineEdit()
        self.quantity_input.setPlaceholderText('Ilość')
        layout.addRow('Wolumen (ilość):', self.quantity_input)
        
        # Przyciski
        buttons_layout = QHBoxLayout()
        
        cancel_button = QPushButton('Anuluj')
        cancel_button.clicked.connect(self.reject)
        cancel_button.setStyleSheet('background-color: #6b7280; color: white; padding: 10px; font-weight: bold;')
        
        save_button = QPushButton('Zapisz')
        save_button.clicked.connect(self.validate_and_accept)
        save_button.setStyleSheet('background-color: #10b981; color: white; padding: 10px; font-weight: bold;')
        
        buttons_layout.addWidget(cancel_button)
        buttons_layout.addWidget(save_button)
        
        layout.addRow(buttons_layout)
        
        self.setLayout(layout)
    
    def on_level_selected(self, index):
        """Aktualizuje cenę zakupu po wybraniu poziomu"""
        price = self.level_combo.itemData(index)
        self.buy_price_input.setText(f"{price:.2f}")
    
    def validate_and_accept(self):
        try:
            # Walidacja ceny zakupu
            buy_price_text = self.buy_price_input.text().strip()
            if not buy_price_text:
                raise ValueError("Wprowadź cenę zakupu")
            
            buy_price = safe_float_convert(buy_price_text, "cena zakupu")
            
            # Walidacja ilości
            quantity_text = self.quantity_input.text().strip()
            if not quantity_text:
                raise ValueError("Wprowadź ilość")
            
            quantity = safe_float_convert(quantity_text, "ilość")
            
            # Pobierz wybrany poziom
            selected_index = self.level_combo.currentIndex()
            selected_level = self.strategy['levels'][selected_index]['level']
            
            self.strategy_data = {
                'buy_price': buy_price,
                'quantity': quantity,
                'selected_level': selected_level
            }
            
            self.accept()
            
        except ValueError as e:
            logger.error(f"Błąd walidacji danych strategii: {str(e)}")
            QMessageBox.warning(self, 'Błąd', f'Błąd walidacji:\n{str(e)}')


# ============================================================
# WINDOWS SESSION MONITOR - Wykrywanie blokady ekranu
# ============================================================

class WindowsSessionMonitor(QThread):
    """
    Monitoruje zdarzenia sesji Windows:
    - Blokada ekranu (Win+L)
    - Odblokowanie ekranu
    - Uśpienie/Hibernacja
    - Wybudzenie
    - Zmiana użytkownika (Fast User Switching)
    - Rozłączenie/Połączenie Remote Desktop
    """
    
    screen_locked = pyqtSignal()
    screen_unlocked = pyqtSignal()
    system_suspend = pyqtSignal()
    system_resume = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.running = True
        self.hwnd = None
        
    def run(self):
        """Główna pętla monitorująca zdarzenia Windows"""
        if sys.platform != 'win32':
            logger.info("Windows Session Monitor: Nie uruchomiono (tylko Windows)")
            return
        
        try:
            # Sprawdź czy wymagane moduły są dostępne
            import win32gui
            import win32api
            import win32con
            
        except ImportError:
            logger.error("Windows Session Monitor: pywin32 nie zainstalowany")
            return
        
        try:
            # Zarejestruj klasę okna
            wc = win32gui.WNDCLASS()
            wc.lpfnWndProc = self._wnd_proc
            wc.lpszClassName = "PortfolioSessionMonitor"
            wc.hInstance = win32api.GetModuleHandle(None)
            
            try:
                class_atom = win32gui.RegisterClass(wc)
            except Exception as e:
                # Klasa już zarejestrowana - to OK
                logger.debug(f"Window class already registered: {e}")
                class_atom = win32gui.WNDCLASS()
                class_atom.lpszClassName = "PortfolioSessionMonitor"
            
            # Stwórz ukryte okno do odbierania komunikatów
            self.hwnd = win32gui.CreateWindow(
                wc.lpszClassName,
                "Portfolio Session Monitor",
                0,  # WS_OVERLAPPED
                0, 0, 0, 0,  # pozycja i rozmiar
                0,  # parent
                0,  # menu
                wc.hInstance,
                None
            )
            
            if not self.hwnd:
                logger.error("Nie udało się utworzyć okna monitora")
                return
            
            # Zarejestruj się do WTS Session Notifications
            WTS_CURRENT_SERVER_HANDLE = 0
            NOTIFY_FOR_THIS_SESSION = 0
            
            wtsapi32 = ctypes.WinDLL('wtsapi32', use_last_error=True)
            wtsapi32.WTSRegisterSessionNotification.argtypes = [
                wintypes.HWND,
                wintypes.DWORD
            ]
            wtsapi32.WTSRegisterSessionNotification.restype = wintypes.BOOL
            
            result = wtsapi32.WTSRegisterSessionNotification(
                self.hwnd,
                NOTIFY_FOR_THIS_SESSION
            )
            
            if not result:
                error = ctypes.get_last_error()
                logger.error(f"WTSRegisterSessionNotification failed: {error}")
                return
            
            logger.info("✅ Windows Session Monitor uruchomiony")
            
            # Message loop
            win32gui.PumpMessages()
            
        except Exception as e:
            logger.error(f"Błąd Windows Session Monitor: {e}", exc_info=True)
    
    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        """Window procedure - odbiera komunikaty Windows"""
        
        # Message types
        WM_WTSSESSION_CHANGE = 0x02B1
        WM_POWERBROADCAST = 0x0218
        
        # WTS Session events
        WTS_CONSOLE_CONNECT = 0x1
        WTS_CONSOLE_DISCONNECT = 0x2
        WTS_REMOTE_CONNECT = 0x3
        WTS_REMOTE_DISCONNECT = 0x4
        WTS_SESSION_LOGON = 0x5
        WTS_SESSION_LOGOFF = 0x6
        WTS_SESSION_LOCK = 0x7
        WTS_SESSION_UNLOCK = 0x8
        WTS_SESSION_REMOTE_CONTROL = 0x9
        
        # Power broadcast events
        PBT_APMSUSPEND = 0x0004
        PBT_APMRESUMESUSPEND = 0x0007
        PBT_APMRESUMEAUTOMATIC = 0x0012
        
        try:
            if msg == WM_WTSSESSION_CHANGE:
                if wparam == WTS_SESSION_LOCK:
                    logger.info("🔒 Windows: Ekran zablokowany (Win+L)")
                    self.screen_locked.emit()
                    
                elif wparam == WTS_SESSION_UNLOCK:
                    logger.info("🔓 Windows: Ekran odblokowany")
                    self.screen_unlocked.emit()
                    
                elif wparam == WTS_SESSION_LOGOFF:
                    logger.info("👋 Windows: Użytkownik wylogowany")
                    self.screen_locked.emit()
                    
                elif wparam == WTS_CONSOLE_DISCONNECT:
                    logger.info("🖥️ Windows: Konsola rozłączona")
                    self.screen_locked.emit()
                    
                elif wparam == WTS_REMOTE_DISCONNECT:
                    logger.info("🌐 Windows: Remote Desktop rozłączony")
                    self.screen_locked.emit()
                    
                elif wparam == WTS_CONSOLE_CONNECT:
                    logger.info("🖥️ Windows: Konsola połączona")
                    # Nie odblokowujemy automatycznie
                    
                elif wparam == WTS_REMOTE_CONNECT:
                    logger.info("🌐 Windows: Remote Desktop połączony")
                    # Nie odblokowujemy automatycznie
            
            elif msg == WM_POWERBROADCAST:
                if wparam == PBT_APMSUSPEND:
                    logger.info("😴 Windows: System przechodzi w tryb uśpienia")
                    self.system_suspend.emit()
                    self.screen_locked.emit()
                    
                elif wparam in (PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC):
                    logger.info("⚡ Windows: System wybudzony z uśpienia")
                    self.system_resume.emit()
                    # Nie odblokowujemy automatycznie - użytkownik musi się zalogować
        
        except Exception as e:
            logger.error(f"Błąd w _wnd_proc: {e}")
        
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)
    
    def stop(self):
        """Zatrzymuje monitoring"""
        self.running = False
        if self.hwnd:
            try:
                import win32gui
                import win32con
                win32gui.PostMessage(self.hwnd, win32con.WM_QUIT, 0, 0)
                logger.info("Windows Session Monitor zatrzymany")
            except:
                pass


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # Pobierz poprawną ścieżkę do bazy danych (obsługa .exe)
        db_path = resource_path('portfolio.db')
        self.db = Database(db_path)
        
        self.current_currency = 'USD'
        self.price_cache = PriceCache(ttl_minutes=5)  # Nowy cache z TTL
        self.company_names_cache = {}  # Cache dla nazw firm - optymalizacja wydajności
        self.is_initialized = False  # Flaga inicjalizacji
        self.current_usd_rate = None  # Aktualny kurs USD/PLN
        self.current_eur_rate = None  # Aktualny kurs EUR/PLN
        self.current_btc_rate = None  # Aktualny kurs BTC/USD
        self.current_eth_rate = None  # Aktualny kurs ETH/USD
        self.current_spx_value = None  # Aktualna wartość S&P 500
        self.exchange_rates_last_update = None  # Timestamp ostatniej aktualizacji kursów (cache)
        
        # Hybrydowy cache - dla instant load
        self.positions_refresh_in_progress = False  # Flaga dla async refresh pozycji
        self.watchlist_refresh_in_progress = False  # Flaga dla async refresh watchlist
        self.last_refresh_time = None
        self.auto_refresh_enabled = True  # Można wyłączyć auto-refresh
        
        # Pasek postępu dla odświeżania cen
        self.progress_bar = None
        self.progress_label = None
        
        # Zmienna dla przechowywania poziomów strategii
        self.current_strategy_levels = None
        
        # Auto-lock timer (sprawdzanie bezczynności)
        self.last_activity_time = datetime.now()
        self.auto_lock_timer = QTimer()
        self.auto_lock_timer.timeout.connect(self.check_auto_lock)
        self.auto_lock_timer.start(60000)  # Sprawdzaj co minutę
        
        # Windows Session Monitor (blokada przy Win+L, Sleep, etc.)
        self.session_monitor = None
        if sys.platform == 'win32':
            try:
                self.session_monitor = WindowsSessionMonitor()
                self.session_monitor.screen_locked.connect(self.on_windows_screen_locked)
                self.session_monitor.screen_unlocked.connect(self.on_windows_screen_unlocked)
                self.session_monitor.system_suspend.connect(self.on_windows_suspend)
                self.session_monitor.system_resume.connect(self.on_windows_resume)
                
                # Uruchom tylko jeśli hasło jest włączone
                if self.db.is_auth_enabled():
                    self.session_monitor.start()
                    logger.info("Windows Session Monitor zainicjalizowany")
            except Exception as e:
                logger.warning(f"Nie udało się uruchomić Windows Session Monitor: {e}")
        
        self.init_ui()
        self.is_initialized = True  # UI gotowe
        
        # Załaduj dane po pełnej inicjalizacji UI
        # ALE TYLKO jeśli nie ma hasła - w przeciwnym razie załaduj po logowaniu
        if not (self.db.is_auth_enabled() and self.db.has_password_set()):
            QTimer.singleShot(100, self.initial_load)
        
        # Auto-refresh co 1 godzinę
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_prices)
        self.timer.start(AUTO_REFRESH_INTERVAL_MS)
    
    def initial_load(self):
        """Pierwsze załadowanie danych bez odświeżania cen"""
        self.load_data()
        
        # Pobierz kursy walut w tle (async) żeby były gotowe gdy user przełączy na PLN
        # To uniknie laga przy pierwszym przełączeniu na PLN
        import threading
        def fetch_rates_bg():
            logger.info("🔄 Pobieranie kursów walut w tle...")
            self.fetch_and_cache_exchange_rates()
            logger.info("✅ Kursy walut pobrane w tle")
        
        thread = threading.Thread(target=fetch_rates_bg, daemon=True)
        thread.start()
        
        # self.refresh_prices()  # Zakomentowano - nie aktualizuj cen przy starcie
    
    # ============================================================
    # AUTO-LOCK I ŚLEDZENIE AKTYWNOŚCI
    # ============================================================
    
    def eventFilter(self, obj, event):
        """Przechwytuje zdarzenia aby śledzić aktywność użytkownika"""
        # Zdarzenia wskazujące na aktywność
        if event.type() in [event.MouseButtonPress, event.MouseMove, 
                           event.KeyPress, event.Wheel]:
            self.last_activity_time = datetime.now()
        
        return super().eventFilter(obj, event)
    
    def check_auto_lock(self):
        """Sprawdza czy aplikację należy zablokować z powodu bezczynności"""
        # Sprawdź czy auto-lock jest włączony
        if not self.db.is_auth_enabled():
            return
        
        auto_lock_enabled = self.db.get_setting('auto_lock_enabled', 'false')
        if auto_lock_enabled.lower() != 'true':
            return
        
        # Sprawdź czas bezczynności
        auto_lock_minutes = int(self.db.get_setting('auto_lock_minutes', '30'))
        inactive_time = (datetime.now() - self.last_activity_time).total_seconds() / 60
        
        if inactive_time >= auto_lock_minutes:
            logger.info(f"Auto-lock: Aplikacja zablokowana po {inactive_time:.0f} min bezczynności")
            self.lock_application()
    
    def lock_application(self):
        """Blokuje aplikację i wymaga ponownego logowania"""
        self.hide()  # Ukryj główne okno całkowicie
        
        dialog = LoginDialog(self.db, self)
        if dialog.exec_() == QDialog.Accepted:
            self.showMaximized()  # Pokaż zmaksymalizowane po poprawnym logowaniu
            self.last_activity_time = datetime.now()  # Resetuj czas
        else:
            # Jeśli użytkownik zamknął dialog - zamknij aplikację
            QApplication.quit()
    
    def manual_logout(self):
        """Ręczne wylogowanie użytkownika (przycisk WYLOGUJ)"""
        reply = QMessageBox.question(
            self,
            'Wylogowanie',
            'Czy na pewno chcesz się wylogować?\n\n'
            'Aplikacja zostanie zablokowana i będziesz musiał wprowadzić hasło ponownie.',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            logger.info("Użytkownik wylogował się ręcznie")
            self.lock_application()
    
    def on_windows_screen_locked(self):
        """Obsługuje blokadę ekranu Windows (Win+L)"""
        if not self.db.is_auth_enabled():
            return
        
        # Sprawdź czy opcja jest włączona
        lock_on_windows = self.db.get_setting('lock_on_windows_lock', 'true')
        if lock_on_windows.lower() != 'true':
            return
        
        logger.info("🔒 Blokowanie aplikacji - blokada Windows")
        self.lock_application()
    
    def on_windows_screen_unlocked(self):
        """Obsługuje odblokowanie ekranu Windows"""
        logger.info("🔓 Windows odblokowany")
        # Aplikacja już czeka na hasło - nic więcej nie robimy
    
    def on_windows_suspend(self):
        """Obsługuje przejście systemu w tryb uśpienia"""
        if not self.db.is_auth_enabled():
            return
        
        lock_on_windows = self.db.get_setting('lock_on_windows_lock', 'true')
        if lock_on_windows.lower() != 'true':
            return
        
        logger.info("😴 Blokowanie aplikacji - system w tryb uśpienia")
        # Aplikacja zostanie zablokowana przez screen_locked signal
    
    def on_windows_resume(self):
        """Obsługuje wybudzenie systemu"""
        logger.info("⚡ System wybudzony")
        # Aplikacja już czeka na hasło - nic więcej nie robimy
    
    def init_ui(self):
        self.setWindowTitle('TurboApka')
        self.setMinimumSize(800, 600)  # Minimalne rozmiary dla małych ekranów
        # NIE pokazuj okna tutaj - dopiero po zalogowaniu w main()
        
        # Główny widget
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        
        main_layout = QVBoxLayout()
        
        # ============================================================
        # PRZYCISKI PRZEŁĄCZANIA MODUŁÓW
        # ============================================================
        module_buttons_layout = QHBoxLayout()
        
        # Przycisk Wyloguj (tylko jeśli hasło włączone) - NA SAMEJ LEWEJ KRAWĘDZI
        if self.db.is_auth_enabled() and self.db.has_password_set():
            self.logout_btn = QPushButton('🔒 WYLOGUJ')
            self.logout_btn.setFont(QFont('Arial', 14, QFont.Bold))
            self.logout_btn.setMinimumHeight(50)
            self.logout_btn.setMinimumWidth(200)
            self.logout_btn.setStyleSheet("""
                QPushButton {
                    background-color: #dc2626;
                    color: white;
                    border-radius: 10px;
                    padding: 10px;
                }
                QPushButton:hover {
                    background-color: #b91c1c;
                }
            """)
            self.logout_btn.clicked.connect(self.manual_logout)
            module_buttons_layout.addWidget(self.logout_btn)
        
        module_buttons_layout.addStretch()
        
        self.portfolio_btn = QPushButton('📊 PORTFOLIO')
        self.portfolio_btn.setFont(QFont('Arial', 14, QFont.Bold))
        self.portfolio_btn.setMinimumHeight(50)
        self.portfolio_btn.setMinimumWidth(200)
        self.portfolio_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                border-radius: 10px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        self.portfolio_btn.clicked.connect(self.show_portfolio_module)
        module_buttons_layout.addWidget(self.portfolio_btn)
        
        self.budget_btn = QPushButton('💰 BUDŻET DOMOWY')
        self.budget_btn.setFont(QFont('Arial', 14, QFont.Bold))
        self.budget_btn.setMinimumHeight(50)
        self.budget_btn.setMinimumWidth(200)
        self.budget_btn.setStyleSheet("""
            QPushButton {
                background-color: #6b7280;
                color: white;
                border-radius: 10px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #4b5563;
            }
        """)
        self.budget_btn.clicked.connect(self.show_budget_module)
        
        # Ukryj przycisk jeśli moduł jest wyłączony
        if not self.db.is_module_enabled('budget'):
            self.budget_btn.hide()
        else:
            module_buttons_layout.addWidget(self.budget_btn)
           
        self.media_btn = QPushButton('📊 MEDIA')
        self.media_btn.setFont(QFont('Arial', 14, QFont.Bold))
        self.media_btn.setMinimumHeight(50)
        self.media_btn.setMinimumWidth(200)
        self.media_btn.setStyleSheet("""
            QPushButton {
                background-color: #6b7280;
                color: white;
                border-radius: 10px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #4b5563;
            }
        """)
        self.media_btn.clicked.connect(self.show_media_module)
        
        # Ukryj przycisk jeśli moduł jest wyłączony
        if not self.db.is_module_enabled('media'):
            self.media_btn.hide()
        else:
            module_buttons_layout.addWidget(self.media_btn)
        
        
        # Przycisk Ustawienia
        self.settings_btn = QPushButton('⚙️ USTAWIENIA')
        self.settings_btn.setFont(QFont('Arial', 14, QFont.Bold))
        self.settings_btn.setMinimumHeight(50)
        self.settings_btn.setMinimumWidth(200)
        self.settings_btn.setStyleSheet("""
            QPushButton {
                background-color: #6b7280;
                color: white;
                border-radius: 10px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #4b5563;
            }
        """)
        self.settings_btn.clicked.connect(self.show_settings_dialog)
        module_buttons_layout.addWidget(self.settings_btn)
        
        module_buttons_layout.addStretch()
        main_layout.addLayout(module_buttons_layout)
        
        # Przycisk odświeżania cen (dostępny globalnie) - po prawej stronie
        refresh_prices_layout = QHBoxLayout()
        refresh_prices_layout.addStretch()  # Przestrzeń po lewej stronie wypycha przycisk w prawo
        
        self.global_refresh_button = QPushButton('🔄 Odśwież ceny')
        self.global_refresh_button.clicked.connect(self.refresh_prices)
        self.global_refresh_button.setFont(QFont('Arial', 12, QFont.Bold))
        self.global_refresh_button.setMinimumHeight(40)
        self.global_refresh_button.setMinimumWidth(180)
        self.global_refresh_button.setStyleSheet("""
            QPushButton {
                background-color: #34d399;
                color: white;
                border-radius: 8px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #10b981;
            }
        """)
        refresh_prices_layout.addWidget(self.global_refresh_button)
        main_layout.addLayout(refresh_prices_layout)
        
        # ============================================================
        # STACKED WIDGET DLA MODUŁÓW
        # ============================================================
        from PyQt5.QtWidgets import QStackedWidget
        self.module_stack = QStackedWidget()
        
        # ============================================================
        # MODUŁ PORTFOLIO
        # ============================================================
        portfolio_widget = QWidget()
        layout = QVBoxLayout()
        
        # Zakładki walut (bez nagłówka)
        currency_tabs = QTabWidget()
        currency_tabs.currentChanged.connect(self.on_currency_changed)
        
        # Style dla zakładek - USD zielony, PLN czerwony, Strategie niebieski
        currency_tabs.setStyleSheet("""
            QTabBar::tab { 
                padding: 18px 50px;
                margin: 0px 5px;
                font-size: 20px;
                font-weight: bold;
                min-width: 100px;
                min-height: 40px;
            }
            QTabBar::tab:first {
                color: #10b981;
            }
            QTabBar::tab:first:selected {
                color: #059669;
            }
            QTabBar::tab:!first:!last {
                color: #ef4444;
            }
            QTabBar::tab:!first:!last:selected {
                color: #dc2626;
            }
            QTabBar::tab:last {
                color: #3b82f6;
            }
            QTabBar::tab:last:selected {
                color: #2563eb;
            }
        """)
        
        # USD Tab
        self.usd_widget = self.create_currency_widget('USD')
        currency_tabs.addTab(self.usd_widget, 'USD')
        
        # PLN Tab
        self.pln_widget = self.create_currency_widget('PLN')
        currency_tabs.addTab(self.pln_widget, 'PLN')
        
        # Strategie Tab
        self.strategies_widget = self.create_strategies_widget()
        currency_tabs.addTab(self.strategies_widget, 'Strategie')
        
        # Dodaj zakładki do głównego layoutu
        layout.addWidget(currency_tabs)
        
        # Kontener na pasek postępu i kursy na dole (cała szerokość)
        bottom_container = QWidget()
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 5, 0, 0)
        bottom_layout.setSpacing(10)
        
        # Font dla statusu
        status_font = QFont('Arial', 11)
        
        # Lewa strona - pasek postępu i status
        progress_container = QWidget()
        progress_layout = QVBoxLayout()
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(5)
        
        # Etykieta statusu
        self.progress_label = QLabel('Gotowy')
        self.progress_label.setFont(status_font)
        self.progress_label.setAlignment(Qt.AlignCenter)
        progress_layout.addWidget(self.progress_label)
        
        # Pasek postępu
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumHeight(30)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat('%v/%m (%p%)')
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #3b82f6;
                border-radius: 5px;
                text-align: center;
                font-size: 12px;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #3b82f6;
            }
        """)
        progress_layout.addWidget(self.progress_bar)
        
        progress_container.setLayout(progress_layout)
        bottom_layout.addWidget(progress_container, 1)  # zajmuje lewą połowę
        
        # Prawa strona - kursy walut i indeksów (od połowy do prawej)
        rates_container = QWidget()
        rates_layout = QHBoxLayout()
        rates_layout.setContentsMargins(0, 0, 0, 0)
        rates_layout.setSpacing(8)
        
        # Kurs USD/PLN
        usd_rate_label = QLabel('USD/PLN: ...')
        usd_rate_label.setFont(QFont('Arial', 12, QFont.Bold))
        usd_rate_label.setStyleSheet('color: #10b981; padding: 8px 16px; background-color: #f0fdf4; border-radius: 5px;')
        usd_rate_label.setObjectName('usd_rate_label')
        usd_rate_label.setAlignment(Qt.AlignCenter)
        rates_layout.addWidget(usd_rate_label)
        
        # Kurs EUR/PLN
        eur_rate_label = QLabel('EUR/PLN: ...')
        eur_rate_label.setFont(QFont('Arial', 12, QFont.Bold))
        eur_rate_label.setStyleSheet('color: #3b82f6; padding: 8px 16px; background-color: #eff6ff; border-radius: 5px;')
        eur_rate_label.setObjectName('eur_rate_label')
        eur_rate_label.setAlignment(Qt.AlignCenter)
        rates_layout.addWidget(eur_rate_label)
        
        # Kurs BTC/USD
        btc_rate_label = QLabel('BTC: ...')
        btc_rate_label.setFont(QFont('Arial', 12, QFont.Bold))
        btc_rate_label.setStyleSheet('color: #f59e0b; padding: 8px 16px; background-color: #fffbeb; border-radius: 5px;')
        btc_rate_label.setObjectName('btc_rate_label')
        btc_rate_label.setAlignment(Qt.AlignCenter)
        rates_layout.addWidget(btc_rate_label)
        
        # Kurs ETH/USD
        eth_rate_label = QLabel('ETH: ...')
        eth_rate_label.setFont(QFont('Arial', 12, QFont.Bold))
        eth_rate_label.setStyleSheet('color: #6366f1; padding: 8px 16px; background-color: #eef2ff; border-radius: 5px;')
        eth_rate_label.setObjectName('eth_rate_label')
        eth_rate_label.setAlignment(Qt.AlignCenter)
        rates_layout.addWidget(eth_rate_label)
        
        # Wartość S&P 500
        spx_value_label = QLabel('SPX: ...')
        spx_value_label.setFont(QFont('Arial', 12, QFont.Bold))
        spx_value_label.setStyleSheet('color: #8b5cf6; padding: 8px 16px; background-color: #f5f3ff; border-radius: 5px;')
        spx_value_label.setObjectName('spx_value_label')
        spx_value_label.setAlignment(Qt.AlignCenter)
        rates_layout.addWidget(spx_value_label)
        
        rates_container.setLayout(rates_layout)
        bottom_layout.addWidget(rates_container, 1)  # zajmuje prawą połowę
        
        bottom_container.setLayout(bottom_layout)
        layout.addWidget(bottom_container)
        
        portfolio_widget.setLayout(layout)
        
        # Dodaj moduł portfolio do stacka
        self.module_stack.addWidget(portfolio_widget)
        
        # ============================================================
        # MODUŁ BUDŻETU DOMOWEGO (tylko jeśli włączony)
        # ============================================================
        if self.db.is_module_enabled('budget'):
            self.budget_widget = BudgetWidget(self.db)
            self.module_stack.addWidget(self.budget_widget)
        else:
            self.budget_widget = None
        
        # MODUŁ MEDIA (tylko jeśli włączony)
        if self.db.is_module_enabled('media'):
            self.media_widget = MediaWidget(self, self.db)
            self.module_stack.addWidget(self.media_widget)
        else:
            self.media_widget = None
        
        # Dodaj stack do głównego layoutu
        main_layout.addWidget(self.module_stack)
        
        main_widget.setLayout(main_layout)
        
        # Status bar (pusty, ale pozostawiamy dla kompatybilności)
        self.statusBar().setFont(status_font)
        
        # Domyślnie pokaż moduł portfolio
        self.show_portfolio_module()
    
    def create_currency_widget(self, currency):
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Sub-tabs (Aktualne / Oczekiwane / Historia)
        sub_tabs = QTabWidget()
        
        # Zwiększ czcionki w zakładkach wewnętrznych i wymuś czarny kolor
        subtabs_font = QFont('Arial', 12, QFont.Bold)
        sub_tabs.setFont(subtabs_font)
        sub_tabs.setStyleSheet("""
            QTabBar::tab { 
                color: black;
                padding: 15px 35px;
                min-width: 200px;
                min-height: 35px;
            }
            QTabBar::tab:selected {
                color: black;
            }
        """)
        
        # Aktualne pozycje
        positions_widget = QWidget()
        positions_layout = QVBoxLayout()
        
        # Przyciski
        buttons_layout = QHBoxLayout()
        
        add_button = QPushButton(f'+ Dodaj pozycję')
        add_button.clicked.connect(lambda: self.add_position(currency))
        add_button.setStyleSheet('background-color: #3b82f6; color: white; padding: 12px; font-weight: bold; font-size: 14px;')
        
        buttons_layout.addWidget(add_button)
        buttons_layout.addStretch()
        
        export_button = QPushButton('📤 Eksportuj pozycje')
        export_button.clicked.connect(lambda: self.export_positions(currency))
        export_button.setStyleSheet('background-color: #f59e0b; color: white; padding: 12px; font-weight: bold; font-size: 14px;')
        
        import_button = QPushButton('📥 Importuj pozycje')
        import_button.clicked.connect(lambda: self.import_positions(currency))
        import_button.setStyleSheet('background-color: #8b5cf6; color: white; padding: 12px; font-weight: bold; font-size: 14px;')
        
        buttons_layout.addWidget(export_button)
        buttons_layout.addWidget(import_button)
        
        positions_layout.addLayout(buttons_layout)
        
        # Podsumowanie dla bieżących pozycji
        positions_summary_layout = QHBoxLayout()
        positions_summary_label = QLabel('Łączny wynik:')
        positions_summary_label.setFont(QFont('Arial', 14, QFont.Bold))
        
        positions_profit_label = QLabel('0.00')
        positions_profit_label.setFont(QFont('Arial', 18, QFont.Bold))
        positions_profit_label.setObjectName(f'positions_profit_{currency}')
        
        positions_summary_layout.addStretch()
        positions_summary_layout.addWidget(positions_summary_label)
        positions_summary_layout.addWidget(positions_profit_label)
        
        positions_layout.addLayout(positions_summary_layout)
        
        # Tabela pozycji
        positions_table = QTableWidget()
        positions_table.setColumnCount(10)
        positions_table.setHorizontalHeaderLabels([
            'Ticker', 'Typ', 'Cena zakupu', 'Cena aktualna', 'Ilość', 
            'Depozyt', 'Zysk/Strata', 'Zysk %', 'Cel (alert)', 'Akcja'
        ])
        
        # Zwiększ czcionkę i pogrub nagłówki
        header_font = QFont('Arial', 12, QFont.Bold)
        positions_table.horizontalHeader().setFont(header_font)
        positions_table.horizontalHeader().setStyleSheet("QHeaderView::section { background-color: #e5e7eb; padding: 8px; }")
        
        # Zwiększ czcionkę dla numerów pozycji (vertical header)
        row_header_font = QFont('Arial', 14, QFont.Bold)
        positions_table.verticalHeader().setFont(row_header_font)
        
        # Zwiększ czcionkę w komórkach
        table_font = QFont('Arial', 11)
        positions_table.setFont(table_font)
        
        positions_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        positions_table.setObjectName(f'positions_{currency}')
        
        positions_layout.addWidget(positions_table)
        positions_widget.setLayout(positions_layout)
        
        sub_tabs.addTab(positions_widget, 'Aktualne')
        
        # Oczekiwane (Watchlist)
        watchlist_widget = QWidget()
        watchlist_layout = QVBoxLayout()
        
        # Przyciski dla watchlisty
        watchlist_buttons_layout = QHBoxLayout()
        
        watchlist_name = 'Oczekiwane USA' if currency == 'USD' else 'Oczekiwane PL'
        add_watchlist_button = QPushButton(f'+ Dodaj do obserwowanych')
        add_watchlist_button.clicked.connect(lambda: self.add_to_watchlist(currency))
        add_watchlist_button.setStyleSheet('background-color: #3b82f6; color: white; padding: 12px; font-weight: bold; font-size: 14px;')
        
        watchlist_buttons_layout.addWidget(add_watchlist_button)
        watchlist_buttons_layout.addStretch()
        
        watchlist_layout.addLayout(watchlist_buttons_layout)
        
        # Tabela watchlisty
        watchlist_table = QTableWidget()
        watchlist_table.setColumnCount(8)
        watchlist_table.setHorizontalHeaderLabels([
            'Ticker', 'Cena aktualna', 'HP1', 'HP2', 'HP3', 'HP4', 'Notatka', 'Akcja'
        ])
        
        # Zwiększ czcionkę i pogrub nagłówki
        header_font = QFont('Arial', 12, QFont.Bold)
        watchlist_table.horizontalHeader().setFont(header_font)
        watchlist_table.horizontalHeader().setStyleSheet("QHeaderView::section { background-color: #e5e7eb; padding: 8px; }")
        
        # Zwiększ czcionkę w komórkach
        table_font = QFont('Arial', 11)
        watchlist_table.setFont(table_font)
        
        watchlist_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        watchlist_table.setObjectName(f'watchlist_{currency}')
        
        watchlist_layout.addWidget(watchlist_table)
        watchlist_widget.setLayout(watchlist_layout)
        
        sub_tabs.addTab(watchlist_widget, watchlist_name)
        
        # Historia
        history_widget = QWidget()
        history_layout = QVBoxLayout()
        
        # Przycisk eksportu historii
        export_history_layout = QHBoxLayout()
        
        export_history_layout.addStretch()
        
        export_history_button = QPushButton('📤 Eksportuj historię')
        export_history_button.clicked.connect(lambda: self.export_history(currency))
        export_history_button.setStyleSheet('background-color: #f59e0b; color: white; padding: 12px; font-weight: bold; font-size: 14px;')
        
        import_history_button = QPushButton('📥 Importuj historię')
        import_history_button.clicked.connect(lambda: self.import_history(currency))
        import_history_button.setStyleSheet('background-color: #8b5cf6; color: white; padding: 12px; font-weight: bold; font-size: 14px;')
        
        export_history_layout.addWidget(export_history_button)
        export_history_layout.addWidget(import_history_button)
        history_layout.addLayout(export_history_layout)
        
        # Podsumowanie
        summary_layout = QHBoxLayout()
        summary_label = QLabel('Łączny wynik:')
        summary_label.setFont(QFont('Arial', 14, QFont.Bold))
        
        profit_label = QLabel('0.00')
        profit_label.setFont(QFont('Arial', 18, QFont.Bold))
        profit_label.setObjectName(f'profit_{currency}')
        
        summary_layout.addStretch()
        summary_layout.addWidget(summary_label)
        summary_layout.addWidget(profit_label)
        
        history_layout.addLayout(summary_layout)
        
        # Tabela historii
        history_table = QTableWidget()
        history_table.setColumnCount(11)
        history_table.setHorizontalHeaderLabels([
            'Ticker', 'Cena zakupu', 'Cena sprzedaży', 'Ilość',
            'Zysk/Strata', 'SWAP', 'Dywidenda', 'Zysk %', 'Data zakupu', 'Data sprzedaży', 'Akcje'
        ])
        
        # Zwiększ czcionkę i pogrub nagłówki
        header_font = QFont('Arial', 12, QFont.Bold)
        history_table.horizontalHeader().setFont(header_font)
        history_table.horizontalHeader().setStyleSheet("QHeaderView::section { background-color: #e5e7eb; padding: 8px; }")
        
        # Zwiększ czcionkę w komórkach
        table_font = QFont('Arial', 11)
        history_table.setFont(table_font)
        
        history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        history_table.setObjectName(f'history_{currency}')
        
        history_layout.addWidget(history_table)
        history_widget.setLayout(history_layout)
        
        sub_tabs.addTab(history_widget, 'Historia')
        
        layout.addWidget(sub_tabs)
        widget.setLayout(layout)
        
        return widget
    
    def create_strategies_widget(self):
        """Tworzy widget z zakładką Strategie"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Sub-tabs dla różnych strategii
        strategy_tabs = QTabWidget()
        
        # Style dla zakładek
        subtabs_font = QFont('Arial', 12, QFont.Bold)
        strategy_tabs.setFont(subtabs_font)
        strategy_tabs.setStyleSheet("""
            QTabBar::tab { 
                color: black;
                padding: 15px 35px;
                min-width: 200px;
                min-height: 35px;
            }
            QTabBar::tab:selected {
                color: black;
            }
        """)
        
        # Zakładka 5-10-15
        strategy_5_10_15_widget = self.create_5_10_15_strategy_widget()
        strategy_tabs.addTab(strategy_5_10_15_widget, '5-10-15')
        
        # Zakładka "Do rozegrania"
        to_play_widget = self.create_to_play_widget()
        strategy_tabs.addTab(to_play_widget, 'Do rozegrania')
        
        # Zakładka "Rozgrywane"
        playing_widget = self.create_playing_widget()
        strategy_tabs.addTab(playing_widget, 'Rozgrywane')
        
        layout.addWidget(strategy_tabs)
        widget.setLayout(layout)
        
        return widget
    
    def create_5_10_15_strategy_widget(self):
        """Tworzy widget dla strategii 5-10-15"""
        widget = QWidget()
        main_layout = QVBoxLayout()
        
        # Spacer nad nagłówkiem
        main_layout.addSpacing(30)
        
        # Nagłówek
        header = QLabel('Obliczanie poziomów zakupów')
        header.setFont(QFont('Arial', 22, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet('color: #3b82f6; padding: 10px;')
        main_layout.addWidget(header)
        
        # Główny układ poziomy (formularz po lewej, wyniki po prawej)
        content_layout = QHBoxLayout()
        
        # ========== LEWA STRONA - FORMULARZ ==========
        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setSpacing(25)
        
        # Formularz wejściowy
        form_widget = QWidget()
        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignLeft)
        form_layout.setSpacing(20)
        
        # Styl dla etykiet - większa czcionka
        label_font = QFont('Arial', 14, QFont.Bold)
        
        # Styl dla pól input - większa czcionka
        input_style = """
            QLineEdit, QComboBox {
                font-size: 14px;
                padding: 10px;
                min-height: 25px;
            }
        """
        
        # Pole tickera
        ticker_layout = QVBoxLayout()
        ticker_label = QLabel('Ticker aktywa:')
        ticker_label.setFont(label_font)
        
        self.strategy_ticker_input = QLineEdit()
        self.strategy_ticker_input.setPlaceholderText('np. CDR.WA, AAPL, BTC-USD')
        self.strategy_ticker_input.setMinimumWidth(300)
        self.strategy_ticker_input.setStyleSheet(input_style)
        ticker_layout.addWidget(self.strategy_ticker_input)
        
        fetch_price_button = QPushButton('📊 Pobierz cenę')
        fetch_price_button.clicked.connect(self.fetch_current_price_for_strategy)
        fetch_price_button.setStyleSheet("""
            QPushButton {
                background-color: #10b981; 
                color: white; 
                padding: 12px; 
                font-weight: bold;
                font-size: 18px;
                border-radius: 5px;
                min-height: 20px;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        ticker_layout.addWidget(fetch_price_button)
        
        form_layout.addRow(ticker_label, ticker_layout)
        
        # Wybór strategii (procent)
        strategy_label = QLabel('Strategia:')
        strategy_label.setFont(label_font)
        
        self.strategy_percent_combo = QComboBox()
        self.strategy_percent_combo.addItems(['5%', '10%', '15%'])
        self.strategy_percent_combo.setMinimumWidth(300)
        self.strategy_percent_combo.setStyleSheet(input_style)
        form_layout.addRow(strategy_label, self.strategy_percent_combo)
        
        # Wybór kierunku (spadki/wzrosty)
        direction_label = QLabel('Kierunek:')
        direction_label.setFont(label_font)
        
        self.strategy_direction_combo = QComboBox()
        self.strategy_direction_combo.addItems(['Spadki (Short)', 'Wzrosty (Long)'])
        self.strategy_direction_combo.setMinimumWidth(300)
        self.strategy_direction_combo.setStyleSheet(input_style)
        form_layout.addRow(direction_label, self.strategy_direction_combo)
        
        # Cena startowa
        start_price_label = QLabel('Cena startowa:')
        start_price_label.setFont(label_font)
        
        self.strategy_start_price_input = QLineEdit()
        self.strategy_start_price_input.setPlaceholderText('np. 280')
        self.strategy_start_price_input.setMinimumWidth(300)
        self.strategy_start_price_input.setStyleSheet(input_style)
        form_layout.addRow(start_price_label, self.strategy_start_price_input)
        
        # Cena końcowa
        end_price_label = QLabel('Cena końcowa:')
        end_price_label.setFont(label_font)
        
        self.strategy_end_price_input = QLineEdit()
        self.strategy_end_price_input.setPlaceholderText('np. 160')
        self.strategy_end_price_input.setMinimumWidth(300)
        self.strategy_end_price_input.setStyleSheet(input_style)
        form_layout.addRow(end_price_label, self.strategy_end_price_input)
        
        form_widget.setLayout(form_layout)
        left_layout.addWidget(form_widget)
        
        # Przyciski jeden pod drugim
        buttons_container = QVBoxLayout()
        buttons_container.setSpacing(10)
        
        calculate_button = QPushButton('🧮 Oblicz poziomy zakupów')
        calculate_button.clicked.connect(self.calculate_strategy_levels)
        calculate_button.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6; 
                color: white; 
                padding: 15px 30px; 
                font-weight: bold; 
                font-size: 18px;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        buttons_container.addWidget(calculate_button)
        
        # Przycisk "Do rozegrania"
        save_to_play_button = QPushButton('📋 Do rozegrania')
        save_to_play_button.clicked.connect(self.save_strategy_to_play)
        save_to_play_button.setStyleSheet("""
            QPushButton {
                background-color: #10b981; 
                color: white; 
                padding: 15px 30px; 
                font-weight: bold; 
                font-size: 18px;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        buttons_container.addWidget(save_to_play_button)
        
        left_layout.addLayout(buttons_container)
        
        left_panel.setLayout(left_layout)
        # Usunięto ograniczenie szerokości - panel dostosuje się do zawartości
        
        content_layout.addWidget(left_panel, 1)  # Proporcja 1
        
        # ========== PRAWA STRONA - WYNIKI ==========
        right_panel = QWidget()
        right_layout = QVBoxLayout()
        
        # Dodaj fixed spacing na górze, aby wyrównać tabelę z polem "Ticker aktywa"
        right_layout.addSpacing(-35)
        
        # Podsumowanie
        self.strategy_summary_label = QLabel('')
        self.strategy_summary_label.setFont(QFont('Arial', 12))
        self.strategy_summary_label.setAlignment(Qt.AlignCenter)
        self.strategy_summary_label.setStyleSheet('color: #10b981; padding: 10px;')
        self.strategy_summary_label.setWordWrap(True)
        right_layout.addWidget(self.strategy_summary_label)
        
        # Tabela poziomów
        self.strategy_levels_table = QTableWidget()
        self.strategy_levels_table.setColumnCount(3)
        self.strategy_levels_table.setHorizontalHeaderLabels([
            'Poziom', 'Cena zakupu', 'Zmiana od poprzedniego'
        ])
        
        # Style tabeli
        header_font = QFont('Arial', 12, QFont.Bold)
        self.strategy_levels_table.horizontalHeader().setFont(header_font)
        self.strategy_levels_table.horizontalHeader().setStyleSheet(
            "QHeaderView::section { background-color: #e5e7eb; padding: 8px; }"
        )
        
        table_font = QFont('Arial', 11)
        self.strategy_levels_table.setFont(table_font)
        self.strategy_levels_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        
        right_layout.addWidget(self.strategy_levels_table)
        
        right_panel.setLayout(right_layout)
        
        content_layout.addWidget(right_panel, 2)  # Proporcja 2
        
        # Dodaj główny układ poziomy do layoutu
        main_layout.addLayout(content_layout)
        
        widget.setLayout(main_layout)
        
        return widget
    
    def fetch_current_price_for_strategy(self):
        """Pobiera aktualną cenę dla tickera w strategii"""
        ticker = self.strategy_ticker_input.text().strip().upper()
        
        if not ticker:
            QMessageBox.warning(self, 'Błąd', 'Wprowadź ticker aktywa')
            return
        
        try:
            self.progress_label.setText(f'Pobieranie ceny {ticker}...')
            QApplication.processEvents()
            
            price = self.fetch_price(ticker)
            
            if price and price > 0:
                self.strategy_start_price_input.setText(f'{price:.2f}')
                QMessageBox.information(self, 'Sukces', 
                    f'Aktualna cena {ticker}: {price:.2f}\n\nWpisz cenę końcową i oblicz poziomy.')
                self.progress_label.setText('Gotowy')
            else:
                QMessageBox.warning(self, 'Błąd', 
                    f'Nie udało się pobrać ceny dla {ticker}.\nSprawdź ticker i spróbuj ponownie.')
                self.progress_label.setText('Błąd')
        
        except Exception as e:
            logger.error(f"Błąd pobierania ceny: {e}")
            QMessageBox.critical(self, 'Błąd', f'Wystąpił błąd: {str(e)}')
            self.progress_label.setText('Błąd')
    
    def calculate_strategy_levels(self):
        """Oblicza poziomy zakupu dla strategii 5-10-15"""
        try:
            # Pobierz dane z formularza
            ticker = self.strategy_ticker_input.text().strip().upper()
            if not ticker:
                QMessageBox.warning(self, 'Błąd', 'Wprowadź ticker aktywa')
                return
            
            start_price_text = self.strategy_start_price_input.text().strip()
            end_price_text = self.strategy_end_price_input.text().strip()
            
            if not start_price_text or not end_price_text:
                QMessageBox.warning(self, 'Błąd', 'Wprowadź cenę startową i końcową')
                return
            
            try:
                start_price = float(start_price_text)
                end_price = float(end_price_text)
            except ValueError:
                QMessageBox.warning(self, 'Błąd', 'Ceny muszą być liczbami')
                return
            
            if start_price <= 0 or end_price <= 0:
                QMessageBox.warning(self, 'Błąd', 'Ceny muszą być większe od 0')
                return
            
            # Pobierz procent strategii
            strategy_text = self.strategy_percent_combo.currentText()
            percent = int(strategy_text.replace('%', ''))
            
            # Pobierz kierunek
            direction = self.strategy_direction_combo.currentText()
            is_short = 'Spadki' in direction
            
            # Walidacja kierunku względem cen
            if is_short and start_price <= end_price:
                QMessageBox.warning(self, 'Błąd', 
                    'Dla strategii na spadki cena startowa musi być wyższa niż końcowa')
                return
            
            if not is_short and start_price >= end_price:
                QMessageBox.warning(self, 'Błąd', 
                    'Dla strategii na wzrosty cena startowa musi być niższa niż końcowa')
                return
            
            # Oblicz poziomy
            levels = []
            current_price = start_price
            level_number = 1
            
            multiplier = 1 - (percent / 100) if is_short else 1 + (percent / 100)
            
            # Dodaj poziom startowy
            levels.append({
                'level': level_number,
                'price': current_price,
                'change': 0
            })
            
            # Oblicz kolejne poziomy
            while True:
                previous_price = current_price
                current_price = current_price * multiplier
                level_number += 1
                
                # Sprawdź czy osiągnięto cenę końcową
                if is_short:
                    if current_price <= end_price:
                        # Dodaj ostatni poziom na cenie końcowej
                        if abs(current_price - end_price) > 0.01:  # tylko jeśli są różne
                            change_percent = ((end_price - previous_price) / previous_price) * 100
                            levels.append({
                                'level': level_number,
                                'price': end_price,
                                'change': change_percent
                            })
                        break
                else:
                    if current_price >= end_price:
                        # Dodaj ostatni poziom na cenie końcowej
                        if abs(current_price - end_price) > 0.01:  # tylko jeśli są różne
                            change_percent = ((end_price - previous_price) / previous_price) * 100
                            levels.append({
                                'level': level_number,
                                'price': end_price,
                                'change': change_percent
                            })
                        break
                
                change_percent = ((current_price - previous_price) / previous_price) * 100
                levels.append({
                    'level': level_number,
                    'price': current_price,
                    'change': change_percent
                })
                
                # Zabezpieczenie przed nieskończoną pętlą
                if level_number > 1000:
                    QMessageBox.warning(self, 'Błąd', 
                        'Zbyt duża różnica między cenami. Spróbuj mniejszej różnicy lub większego procentu.')
                    return
            
            # Wyświetl podsumowanie
            price_diff = abs(end_price - start_price)
            price_diff_percent = (price_diff / start_price) * 100
            
            summary_text = (f'Ticker: {ticker} | Strategia: {percent}% | Kierunek: {"SPADKI" if is_short else "WZROSTY"}\n'
                          f'Cena startowa: {start_price:.2f} → Cena końcowa: {end_price:.2f}\n'
                          f'Różnica: {price_diff:.2f} ({price_diff_percent:.1f}%) | Liczba poziomów: {len(levels)}')
            
            self.strategy_summary_label.setText(summary_text)
            
            # Wypełnij tabelę
            self.strategy_levels_table.setRowCount(len(levels))
            
            for i, level in enumerate(levels):
                # Poziom
                level_item = QTableWidgetItem(f"Poziom {level['level']}")
                level_item.setTextAlignment(Qt.AlignCenter)
                level_item.setFont(QFont('Arial', 11, QFont.Bold))
                self.strategy_levels_table.setItem(i, 0, level_item)
                
                # Cena
                price_item = QTableWidgetItem(f"{level['price']:.2f}")
                price_item.setTextAlignment(Qt.AlignCenter)
                price_item.setFont(QFont('Arial', 11))
                
                # Koloruj pierwszy i ostatni poziom
                if i == 0:
                    price_item.setBackground(QColor(220, 252, 231))  # zielony
                elif i == len(levels) - 1:
                    price_item.setBackground(QColor(254, 242, 242))  # czerwony
                
                self.strategy_levels_table.setItem(i, 1, price_item)
                
                # Zmiana procentowa
                change_text = f"{level['change']:+.2f}%" if level['change'] != 0 else "START"
                change_item = QTableWidgetItem(change_text)
                change_item.setTextAlignment(Qt.AlignCenter)
                change_item.setFont(QFont('Arial', 11))
                
                if level['change'] < 0:
                    change_item.setForeground(QColor(239, 68, 68))  # czerwony
                elif level['change'] > 0:
                    change_item.setForeground(QColor(16, 185, 129))  # zielony
                
                self.strategy_levels_table.setItem(i, 2, change_item)
            
            # Zapisz poziomy do późniejszego eksportu
            self.current_strategy_levels = {
                'ticker': ticker,
                'strategy': percent,
                'direction': 'Spadki' if is_short else 'Wzrosty',
                'start_price': start_price,
                'end_price': end_price,
                'levels': levels
            }
            
            logger.info(f"Obliczono {len(levels)} poziomów dla {ticker}")
            
        except Exception as e:
            logger.error(f"Błąd obliczania strategii: {e}")
            logger.exception("Szczegóły błędu:")
            QMessageBox.critical(self, 'Błąd', f'Wystąpił błąd podczas obliczeń:\n{str(e)}')
    
    def save_strategy_to_play(self):
        """Zapisuje wyliczone poziomy do zakładki 'Do rozegrania'"""
        try:
            if not hasattr(self, 'current_strategy_levels'):
                QMessageBox.warning(self, 'Błąd', 'Najpierw oblicz poziomy zakupów!')
                return
            
            levels = self.current_strategy_levels
            
            # Zapisz do bazy danych
            self.db.add_strategy_to_play(
                ticker=levels['ticker'],
                strategy_percent=levels['strategy'],
                direction=levels['direction'],
                levels=levels['levels']
            )
            
            QMessageBox.information(self, 'Sukces', 
                f'Strategia dla {levels["ticker"]} została dodana do "Do rozegrania"!')
            
            logger.info(f"Zapisano strategię do rozegrania: {levels['ticker']}")
            
            # Odśwież zakładkę "Do rozegrania"
            self.load_strategies_to_play()
            
        except Exception as e:
            logger.error(f"Błąd zapisywania strategii: {e}")
            QMessageBox.critical(self, 'Błąd', f'Wystąpił błąd:\n{str(e)}')
    
    def create_to_play_widget(self):
        """Tworzy widget dla zakładki 'Do rozegrania'"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Nagłówek
        header = QLabel('Strategie zaplanowane do rozegrania')
        header.setFont(QFont('Arial', 16, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet('color: #3b82f6; padding: 10px;')
        layout.addWidget(header)
        
        # Tabela strategii - początkowo z podstawowymi kolumnami
        self.to_play_table = QTableWidget()
        self.to_play_table.setColumnCount(4)  # Ticker, Strategia, Kierunek, Akcje
        self.to_play_table.setHorizontalHeaderLabels([
            'Ticker', 'Strategia', 'Kierunek', 'Akcje'
        ])
        
        # Style tabeli
        header_font = QFont('Arial', 12, QFont.Bold)
        self.to_play_table.horizontalHeader().setFont(header_font)
        self.to_play_table.horizontalHeader().setStyleSheet(
            "QHeaderView::section { background-color: #e5e7eb; padding: 8px; }"
        )
        
        table_font = QFont('Arial', 11)
        self.to_play_table.setFont(table_font)
        self.to_play_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        
        layout.addWidget(self.to_play_table)
        
        widget.setLayout(layout)
        return widget
    
    def create_playing_widget(self):
        """Tworzy widget dla zakładki 'Rozgrywane'"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Nagłówek
        header = QLabel('Aktywnie rozgrywane strategie')
        header.setFont(QFont('Arial', 16, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet('color: #10b981; padding: 10px;')
        layout.addWidget(header)
        
        # Tabela rozgrywanych strategii
        self.playing_table = QTableWidget()
        self.playing_table.setColumnCount(8)
        self.playing_table.setHorizontalHeaderLabels([
            'Ticker', 'Cena zakupu', 'Ilość', 'Cena bieżąca', 
            'Cena zamknięcia', 'Zysk/Strata', 'Zysk %', 'Akcje'
        ])
        
        # Style tabeli
        header_font = QFont('Arial', 12, QFont.Bold)
        self.playing_table.horizontalHeader().setFont(header_font)
        self.playing_table.horizontalHeader().setStyleSheet(
            "QHeaderView::section { background-color: #e5e7eb; padding: 8px; }"
        )
        
        table_font = QFont('Arial', 11)
        self.playing_table.setFont(table_font)
        self.playing_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        
        layout.addWidget(self.playing_table)
        
        widget.setLayout(layout)
        return widget
    
    def load_strategies_to_play(self):
        """Ładuje strategie do rozegrania z bazy danych"""
        try:
            strategies = self.db.get_strategies_to_play()
            
            if not strategies:
                self.to_play_table.setRowCount(0)
                return
            
            # Znajdź maksymalną liczbę poziomów
            max_levels = max(len(s['levels']) for s in strategies)
            
            # Ustaw liczbę kolumn: Ticker + Strategia + Kierunek + Poziomy + Akcje
            num_columns = 3 + max_levels + 1
            self.to_play_table.setColumnCount(num_columns)
            
            # Ustaw nagłówki
            headers = ['Ticker', 'Strategia', 'Kierunek']
            for i in range(max_levels):
                headers.append(f'Poziom {i+1}')
            headers.append('Akcje')
            self.to_play_table.setHorizontalHeaderLabels(headers)
            
            self.to_play_table.setRowCount(len(strategies))
            
            for row_idx, strategy in enumerate(strategies):
                # Ticker
                ticker_item = QTableWidgetItem(strategy['ticker'])
                ticker_item.setTextAlignment(Qt.AlignCenter)
                ticker_item.setFont(QFont('Arial', 11, QFont.Bold))
                self.to_play_table.setItem(row_idx, 0, ticker_item)
                
                # Strategia
                strategy_item = QTableWidgetItem(f"{strategy['strategy_percent']}%")
                strategy_item.setTextAlignment(Qt.AlignCenter)
                self.to_play_table.setItem(row_idx, 1, strategy_item)
                
                # Kierunek
                direction_item = QTableWidgetItem(strategy['direction'])
                direction_item.setTextAlignment(Qt.AlignCenter)
                self.to_play_table.setItem(row_idx, 2, direction_item)
                
                # Wyświetl wszystkie poziomy
                levels = strategy['levels']
                opened_levels = strategy.get('opened_levels', [])
                
                for i, level in enumerate(levels):
                    level_price = level['price']
                    level_number = level['level']
                    
                    # Sprawdź czy poziom został otwarty
                    if level_number in opened_levels:
                        level_item = QTableWidgetItem(f"✅ {level_price:.2f}")
                        level_item.setBackground(QColor(220, 252, 231))  # Zielone tło
                    else:
                        level_item = QTableWidgetItem(f"{level_price:.2f}")
                    
                    level_item.setTextAlignment(Qt.AlignCenter)
                    self.to_play_table.setItem(row_idx, 3 + i, level_item)
                
                # Przycisk "Rozegraj"
                play_button = QPushButton('▶ Rozegraj')
                play_button.setStyleSheet("""
                    QPushButton {
                        background-color: #10b981;
                        color: white;
                        padding: 8px;
                        font-weight: bold;
                        border-radius: 5px;
                    }
                    QPushButton:hover {
                        background-color: #059669;
                    }
                """)
                play_button.clicked.connect(
                    lambda checked, s=strategy: self.open_play_dialog(s)
                )
                self.to_play_table.setCellWidget(row_idx, num_columns - 1, play_button)
            
            logger.info(f"Załadowano {len(strategies)} strategii do rozegrania")
            
        except Exception as e:
            logger.error(f"Błąd ładowania strategii do rozegrania: {e}")
            logger.exception("Szczegóły błędu:")
    
    def open_play_dialog(self, strategy):
        """Otwiera dialog do wprowadzenia ceny zakupu"""
        try:
            dialog = PlayStrategyDialog(strategy, self)
            if dialog.exec_() == QDialog.Accepted:
                data = dialog.strategy_data
                selected_level = data['selected_level']
                
                # Oblicz cenę zamknięcia
                close_price = data['buy_price'] * (1 + strategy['strategy_percent'] / 100)
                
                # Dodaj do rozgrywanych z informacją o kierunku
                self.db.add_strategy_playing(
                    ticker=strategy['ticker'],
                    strategy_percent=strategy['strategy_percent'],
                    buy_price=data['buy_price'],
                    quantity=data['quantity'],
                    close_price=close_price,
                    direction=strategy['direction']  # Przekazujemy kierunek
                )
                
                # Oznacz poziom jako otwarty (NIE usuwaj strategii)
                self.db.mark_level_as_opened(strategy['id'], selected_level)
                
                QMessageBox.information(self, 'Sukces', 
                    f'Strategia dla {strategy["ticker"]} na poziomie {selected_level} została dodana do "Rozgrywane"!\n\n'
                    f'Poziom został oznaczony zieloną strzałką.')
                
                # Odśwież obie zakładki
                self.load_strategies_to_play()
                self.load_strategies_playing()
                
        except Exception as e:
            logger.error(f"Błąd otwierania dialogu rozgrywki: {e}")
            logger.exception("Szczegóły błędu:")
            QMessageBox.critical(self, 'Błąd', f'Wystąpił błąd:\n{str(e)}')
    
    def load_strategies_playing(self):
        """Ładuje aktywnie rozgrywane strategie z bazy danych"""
        try:
            strategies = self.db.get_strategies_playing()
            
            self.playing_table.setRowCount(len(strategies))
            
            # OPTYMALIZACJA: BATCH DOWNLOAD wszystkich cen naraz!
            tickers = [strategy['ticker'] for strategy in strategies]
            prices = self.fetch_multiple_prices_batch(tickers) if tickers else {}
            logger.info(f"Batch download cen dla {len(tickers)} strategii playing zakończony")
            
            for row_idx, strategy in enumerate(strategies):
                # Ticker
                ticker_item = QTableWidgetItem(strategy['ticker'])
                ticker_item.setTextAlignment(Qt.AlignCenter)
                ticker_item.setFont(QFont('Arial', 11, QFont.Bold))
                self.playing_table.setItem(row_idx, 0, ticker_item)
                
                # Cena zakupu
                buy_price_item = QTableWidgetItem(f"{strategy['buy_price']:.2f}")
                buy_price_item.setTextAlignment(Qt.AlignCenter)
                self.playing_table.setItem(row_idx, 1, buy_price_item)
                
                # Ilość
                quantity_item = QTableWidgetItem(f"{strategy['quantity']:.2f}")
                quantity_item.setTextAlignment(Qt.AlignCenter)
                self.playing_table.setItem(row_idx, 2, quantity_item)
                
                # OPTYMALIZACJA: Użyj już pobranej ceny!
                current_price = prices.get(strategy['ticker'], None)
                current_price_item = QTableWidgetItem(
                    f"{current_price:.2f}" if current_price else "N/A"
                )
                current_price_item.setTextAlignment(Qt.AlignCenter)
                self.playing_table.setItem(row_idx, 3, current_price_item)
                
                # Cena zamknięcia
                close_price_item = QTableWidgetItem(f"{strategy['close_price']:.2f}")
                close_price_item.setTextAlignment(Qt.AlignCenter)
                self.playing_table.setItem(row_idx, 4, close_price_item)
                
                # Pobierz kierunek strategii bezpośrednio z rekordu
                is_short = 'Spadki' in strategy.get('direction', 'Wzrosty')
                
                # Oblicz zysk/stratę - RÓŻNE WZORY DLA WZROSTÓW I SPADKÓW
                if current_price and current_price > 0:
                    if is_short:
                        # Dla spadków (Short)
                        profit = (strategy['buy_price'] - current_price) * strategy['quantity'] * -1
                        profit_percent = ((strategy['buy_price'] - current_price) / strategy['buy_price']) * -100
                    else:
                        # Dla wzrostów (Long)
                        profit = (current_price - strategy['buy_price']) * strategy['quantity']
                        profit_percent = ((current_price - strategy['buy_price']) / strategy['buy_price']) * 100
                    
                    logger.debug(f"Obliczanie zysku dla {strategy['ticker']}: "
                               f"kierunek={'SHORT' if is_short else 'LONG'}, "
                               f"current={current_price}, buy={strategy['buy_price']}, "
                               f"qty={strategy['quantity']}, profit={profit}, profit%={profit_percent}")
                    
                    profit_item = QTableWidgetItem(f"{profit:.2f}")
                    profit_item.setTextAlignment(Qt.AlignCenter)
                    
                    if profit >= 0:
                        profit_item.setForeground(QColor(16, 185, 129))
                    else:
                        profit_item.setForeground(QColor(239, 68, 68))
                    
                    self.playing_table.setItem(row_idx, 5, profit_item)
                    
                    profit_percent_item = QTableWidgetItem(f"{profit_percent:+.2f}%")
                    profit_percent_item.setTextAlignment(Qt.AlignCenter)
                    
                    if profit_percent >= 0:
                        profit_percent_item.setForeground(QColor(16, 185, 129))
                    else:
                        profit_percent_item.setForeground(QColor(239, 68, 68))
                    
                    self.playing_table.setItem(row_idx, 6, profit_percent_item)
                    
                    # Sprawdź czy osiągnięto cel
                    target_reached = False
                    if is_short:
                        # Dla short osiągamy cel gdy cena spada
                        target_reached = current_price <= strategy['close_price']
                    else:
                        # Dla long osiągamy cel gdy cena rośnie
                        target_reached = current_price >= strategy['close_price']
                    
                    if target_reached:
                        # Oznacz wiersz na zielono
                        for col in range(7):
                            item = self.playing_table.item(row_idx, col)
                            if item:
                                item.setBackground(ALERT_COLOR_GREEN)
                else:
                    # Jeśli nie ma ceny, pokaż N/A
                    na_item_profit = QTableWidgetItem("N/A")
                    na_item_profit.setTextAlignment(Qt.AlignCenter)
                    self.playing_table.setItem(row_idx, 5, na_item_profit)
                    
                    na_item_percent = QTableWidgetItem("N/A")
                    na_item_percent.setTextAlignment(Qt.AlignCenter)
                    self.playing_table.setItem(row_idx, 6, na_item_percent)
                
                # Przycisk "Usuń"
                delete_button = QPushButton('🗑️ Usuń')
                delete_button.setStyleSheet("""
                    QPushButton {
                        background-color: #ef4444;
                        color: white;
                        padding: 8px;
                        font-weight: bold;
                        border-radius: 5px;
                    }
                    QPushButton:hover {
                        background-color: #dc2626;
                    }
                """)
                delete_button.clicked.connect(
                    lambda checked, s=strategy: self.delete_playing_strategy(s)
                )
                self.playing_table.setCellWidget(row_idx, 7, delete_button)
            
            logger.info(f"Załadowano {len(strategies)} rozgrywanych strategii")
            
        except Exception as e:
            logger.error(f"Błąd ładowania rozgrywanych strategii: {e}")
    
    def delete_playing_strategy(self, strategy):
        """Usuwa rozgrywaną strategię"""
        try:
            reply = QMessageBox.question(self, 'Potwierdzenie', 
                f'Czy na pewno chcesz usunąć strategię dla {strategy["ticker"]}?',
                QMessageBox.Yes | QMessageBox.No)
            
            if reply == QMessageBox.Yes:
                self.db.delete_strategy_playing(strategy['id'])
                QMessageBox.information(self, 'Sukces', 'Strategia została usunięta!')
                self.load_strategies_playing()
                
        except Exception as e:
            logger.error(f"Błąd usuwania strategii: {e}")
            QMessageBox.critical(self, 'Błąd', f'Wystąpił błąd:\n{str(e)}')
    
    
    def on_currency_changed(self, index):
        # Nie zmieniaj waluty jeśli UI nie jest jeszcze gotowe
        if not self.is_initialized:
            return
        
        # Index 0 = USD, 1 = PLN, 2 = Strategie (nie zmienia waluty)
        if index == 2:
            # Zakładka Strategie - nie zmieniaj waluty
            return
            
        self.current_currency = 'USD' if index == 0 else 'PLN'
        self.load_data()
    
    def add_position(self, currency, prefill_ticker=None, prefill_data=None):
        logger.info(f"Otwieranie okna dodawania pozycji dla waluty: {currency}")
        
        try:
            dialog = AddPositionDialog(currency, self, prefill_ticker=prefill_ticker, prefill_data=prefill_data)
            if dialog.exec_() == QDialog.Accepted:
                data = dialog.position_data
                
                logger.info(f"Dodawanie nowej pozycji: {data}")
                
                # Pobierz aktualną cenę
                self.progress_label.setText('Sprawdzam ticker...')
                QApplication.processEvents()
                
                logger.info(f"Pobieranie ceny dla tickera: {data['ticker']}")
                price = self.fetch_price(data['ticker'])
                
                if price is None:
                    logger.warning(f"Nie udało się pobrać ceny dla {data['ticker']}")
                    
                    # Pokaż komunikat z pytaniem czy użytkownik chce poprawić dane
                    reply = QMessageBox.warning(self, 'Błąd', 
                        f'Nie udało się pobrać ceny dla {data["ticker"]}.\n'
                        'Sprawdź ticker (np. AAPL, PKO.WA)\n\n'
                        'Szczegóły w pliku Logs/Log_*.txt\n\n'
                        'Czy chcesz poprawić ticker i spróbować ponownie?',
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.Yes)
                    
                    self.progress_label.setText('Gotowy')
                    
                    # Jeśli użytkownik chce poprawić, wywołaj ponownie okno z danymi
                    if reply == QMessageBox.Yes:
                        self.add_position(currency, prefill_data=data)
                    
                    return
                
                logger.info(f"Cena pobrana pomyślnie: {price}")
                
                # Dodaj do bazy
                position_id = self.db.add_position(
                    ticker=data['ticker'],
                    currency=currency,
                    buy_price=data['buy_price'],
                    quantity=data['quantity'],
                    usd_rate=data['usd_rate'],
                    eur_rate=data.get('eur_rate'),
                    alert_price=data['alert_price'],
                    purchase_date=data['buy_date'],
                    instrument_type=data.get('instrument_type', 'Akcje'),
                    leverage=data.get('leverage'),
                    direction=data.get('direction', 'Long'),
                    swap_daily=data.get('swap_daily'),
                    dividend=data.get('dividend')
                )
                
                logger.warning(f"Pozycja dodana do bazy z ID: {position_id}")
                
                # Sprawdź czy ticker był w watchliście i zaktualizuj poziomy HP
                try:
                    removed = self.db.process_triggered_hp(data['ticker'], currency)
                    if removed:
                        logger.info(f"Ticker {data['ticker']} usunięto z watchlisty (brak kolejnych poziomów HP)")
                    else:
                        logger.info(f"Zaktualizowano poziomy HP dla {data['ticker']} w watchliście")
                except Exception as e:
                    logger.warning(f"Błąd podczas aktualizacji watchlisty dla {data['ticker']}: {e}")
                
                self.progress_label.setText(f'Dodano {data["ticker"]}')
                self.load_data()
        
        except Exception as e:
            logger.error(f"Błąd w add_position: {type(e).__name__} - {str(e)}")
            logger.exception("Szczegóły błędu:")
            QMessageBox.critical(self, 'Błąd', 
                f'Wystąpił błąd podczas dodawania pozycji:\n{str(e)}\n\n'
                f'Sprawdź logi w folderze Logs/')
            self.progress_label.setText('Błąd')
    
    def fetch_price(self, ticker, force_refresh=False):
        """
        Pobiera aktualną cenę z Yahoo Finance z wykorzystaniem PriceCache
        
        Args:
            ticker: Symbol spółki
            force_refresh: Wymusza pobranie ceny z API (pomija cache)
        
        Returns:
            Cena jako float lub None
        """
        # Sprawdź cache (jeśli nie wymuszono odświeżenia)
        if not force_refresh:
            cached_price = self.price_cache.get(ticker)
            if cached_price is not None:
                logger.debug(f"Cena dla {ticker} pobrana z cache: {cached_price}")
                return cached_price
        
        logger.info(f"Pobieranie ceny dla tickera: {ticker}")
        
        try:
            logger.debug(f"Tworzenie obiektu yfinance.Ticker('{ticker}')")
            stock = yf.Ticker(ticker)
            
            logger.debug("Pobieranie info z yfinance...")
            info = stock.info
            
            logger.debug(f"Otrzymano info, klucze: {list(info.keys())[:10]}...")
            
            # Próbuj różne źródła ceny
            price = None
            price_sources = [
                ('currentPrice', info.get('currentPrice')),
                ('regularMarketPrice', info.get('regularMarketPrice')),
                ('previousClose', info.get('previousClose'))
            ]
            
            for source_name, source_value in price_sources:
                logger.debug(f"Sprawdzam {source_name}: {source_value}")
                if source_value:
                    price = source_value
                    logger.info(f"Znaleziono cenę w {source_name}: {price}")
                    break
            
            if price:
                price_float = float(price)
                # Zapisz do cache
                self.price_cache.set(ticker, price_float)
                logger.info(f"Sukces! Cena dla {ticker}: {price_float}")
                return price_float
            else:
                logger.warning(f"Nie znaleziono ceny dla {ticker} w żadnym źródle")
                logger.debug(f"Dostępne klucze w info: {list(info.keys())}")
                return None
                
        except Exception as e:
            logger.error(f"Błąd pobierania ceny dla {ticker}: {type(e).__name__} - {str(e)}")
            logger.exception("Szczegóły błędu:")
            return None
    
    def fetch_company_name(self, ticker):
        """Pobiera nazwę spółki z Yahoo Finance z wykorzystaniem cache"""
        # Sprawdź cache
        if ticker in self.company_names_cache:
            logger.debug(f"Nazwa spółki dla {ticker} pobrana z cache")
            return self.company_names_cache[ticker]
        
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            name = info.get('longName') or info.get('shortName', ticker)
            
            # Zapisz do cache
            self.company_names_cache[ticker] = name
            logger.debug(f"Nazwa spółki dla {ticker} pobrana z API: {name}")
            return name
        except Exception as e:
            logger.error(f"Błąd pobierania nazwy dla {ticker}: {str(e)}")
            # W przypadku błędu, zapisz ticker do cache, żeby nie próbować ponownie
            self.company_names_cache[ticker] = ticker
            return ticker
    
    def fetch_multiple_prices_batch(self, tickers):
        """
        OPTYMALIZACJA: Pobiera ceny wielu tickerów JEDNOCZEŚNIE (batch download)
        
        Args:
            tickers: Lista symboli spółek
            
        Returns:
            Dictionary {ticker: cena} dla wszystkich tickerów
        """
        if not tickers:
            return {}
        
        logger.info(f"BATCH DOWNLOAD: Pobieranie cen dla {len(tickers)} tickerów naraz...")
        start_time = time.time()
        
        prices = {}
        uncached_tickers = []
        
        for ticker in tickers:
            cached_price = self.price_cache.get(ticker)
            if cached_price is not None:
                prices[ticker] = cached_price
                logger.debug(f"Cache HIT: {ticker} = ${cached_price:.2f}")
            else:
                uncached_tickers.append(ticker)
                logger.debug(f"Cache MISS: {ticker}")
        
        logger.info(f"Cache: {len(prices)}/{len(tickers)} trafień, pobieranie {len(uncached_tickers)} z API...")
        
        if uncached_tickers:
            try:
                logger.info(f"Wykonuję batch download dla {len(uncached_tickers)} tickerów...")
                
                data = yf.download(
                    tickers=uncached_tickers,
                    period='1d',
                    interval='1d',
                    group_by='ticker',
                    threads=True,
                    progress=False
                )
                
                api_time = time.time() - start_time
                logger.info(f"API response w {api_time:.2f}s")
                
                if len(uncached_tickers) == 1:
                    ticker = uncached_tickers[0]
                    
                    if not data.empty and 'Close' in data.columns:
                        try:
                            price = float(data['Close'].iloc[-1])
                            prices[ticker] = price
                            self.price_cache.set(ticker, price)
                            logger.info(f"✓ {ticker}: ${price:.2f}")
                        except (ValueError, IndexError) as e:
                            logger.warning(f"✗ {ticker}: Błąd parsowania - {e}")
                            prices[ticker] = 0.0
                    else:
                        logger.warning(f"✗ {ticker}: Brak danych")
                        prices[ticker] = 0.0
                
                else:
                    for ticker in uncached_tickers:
                        try:
                            if ticker in data.columns.levels[0]:
                                close_data = data[ticker]['Close']
                                
                                if not close_data.empty:
                                    last_price = close_data.iloc[-1]
                                    
                                    if not pd.isna(last_price):
                                        price = float(last_price)
                                        prices[ticker] = price
                                        self.price_cache.set(ticker, price)
                                        logger.info(f"✓ {ticker}: ${price:.2f}")
                                    else:
                                        logger.warning(f"✗ {ticker}: Cena NaN")
                                        prices[ticker] = 0.0
                                else:
                                    logger.warning(f"✗ {ticker}: Brak danych Close")
                                    prices[ticker] = 0.0
                            else:
                                logger.warning(f"✗ {ticker}: Nie znaleziony w wynikach")
                                prices[ticker] = 0.0
                        
                        except (KeyError, IndexError, AttributeError, ValueError) as e:
                            logger.error(f"✗ {ticker}: Błąd - {type(e).__name__}: {e}")
                            prices[ticker] = 0.0
            
            except Exception as e:
                logger.error(f"Krytyczny błąd batch download: {type(e).__name__} - {e}")
                for ticker in uncached_tickers:
                    prices[ticker] = 0.0
        
        total_time = time.time() - start_time
        success_rate = (len([p for p in prices.values() if p > 0]) / len(tickers) * 100) if tickers else 0
        
        logger.info(f"✅ BATCH DOWNLOAD zakończony w {total_time:.2f}s")
        logger.info(f"   Sukces: {success_rate:.1f}% ({len([p for p in prices.values() if p > 0])}/{len(tickers)})")
        logger.info(f"   {self.price_cache.get_stats()}")
        
        return prices
    
    def fetch_multiple_prices_batch_with_progress(self, tickers):
        """
        Pobiera ceny wielu tickerów z aktualizacją paska postępu
        
        Args:
            tickers: Lista symboli spółek
            
        Returns:
            Dictionary {ticker: cena} dla wszystkich tickerów
        """
        if not tickers:
            return {}
        
        logger.info(f"BATCH DOWNLOAD: Pobieranie cen dla {len(tickers)} tickerów naraz...")
        start_time = time.time()
        
        prices = {}
        uncached_tickers = []
        
        # Sprawdź cache
        for i, ticker in enumerate(tickers):
            cached_price = self.price_cache.get(ticker)
            if cached_price is not None:
                prices[ticker] = cached_price
                logger.debug(f"Cache HIT: {ticker} = ${cached_price:.2f}")
            else:
                uncached_tickers.append(ticker)
                logger.debug(f"Cache MISS: {ticker}")
            
            # Aktualizuj postęp dla cache
            if i % 10 == 0:  # Co 10 tickerów
                self.progress_bar.setValue(i)
                self.progress_label.setText(f'Sprawdzanie cache ({i}/{len(tickers)})...')
                QApplication.processEvents()
        
        logger.info(f"Cache: {len(prices)}/{len(tickers)} trafień, pobieranie {len(uncached_tickers)} z API...")
        
        if uncached_tickers:
            try:
                logger.info(f"Wykonuję batch download dla {len(uncached_tickers)} tickerów...")
                self.progress_label.setText('Pobieranie danych...')
                QApplication.processEvents()
                
                data = yf.download(
                    tickers=uncached_tickers,
                    period='1d',
                    interval='1d',
                    group_by='ticker',
                    threads=True,
                    progress=False
                )
                
                api_time = time.time() - start_time
                logger.info(f"API response w {api_time:.2f}s")
                
                # Przetwarzanie danych
                if len(uncached_tickers) == 1:
                    ticker = uncached_tickers[0]
                    
                    if not data.empty and 'Close' in data.columns:
                        try:
                            price = float(data['Close'].iloc[-1])
                            prices[ticker] = price
                            self.price_cache.set(ticker, price)
                            logger.info(f"✓ {ticker}: ${price:.2f}")
                        except (ValueError, IndexError) as e:
                            logger.warning(f"✗ {ticker}: Błąd parsowania - {e}")
                            prices[ticker] = 0.0
                    else:
                        logger.warning(f"✗ {ticker}: Brak danych")
                        prices[ticker] = 0.0
                    
                    self.progress_bar.setValue(len(tickers))
                    QApplication.processEvents()
                
                else:
                    # Przetwarzaj każdy ticker z aktualizacją postępu
                    for i, ticker in enumerate(uncached_tickers):
                        try:
                            if ticker in data.columns.levels[0]:
                                close_data = data[ticker]['Close']
                                
                                if not close_data.empty:
                                    last_price = close_data.iloc[-1]
                                    
                                    if not pd.isna(last_price):
                                        price = float(last_price)
                                        prices[ticker] = price
                                        self.price_cache.set(ticker, price)
                                        logger.info(f"✓ {ticker}: ${price:.2f}")
                                    else:
                                        logger.warning(f"✗ {ticker}: Cena NaN")
                                        prices[ticker] = 0.0
                                else:
                                    logger.warning(f"✗ {ticker}: Brak danych Close")
                                    prices[ticker] = 0.0
                            else:
                                logger.warning(f"✗ {ticker}: Nie znaleziony w wynikach")
                                prices[ticker] = 0.0
                        
                        except (KeyError, IndexError, AttributeError, ValueError) as e:
                            logger.error(f"✗ {ticker}: Błąd - {type(e).__name__}: {e}")
                            prices[ticker] = 0.0
                        
                        # Aktualizuj postęp
                        current_progress = len(prices)
                        self.progress_bar.setValue(current_progress)
                        self.progress_label.setText(f'Przetwarzanie ({current_progress}/{len(tickers)})...')
                        if i % 5 == 0:  # Co 5 tickerów
                            QApplication.processEvents()
            
            except Exception as e:
                logger.error(f"Krytyczny błąd batch download: {type(e).__name__} - {e}")
                for ticker in uncached_tickers:
                    prices[ticker] = 0.0
        
        # Końcowa aktualizacja postępu
        self.progress_bar.setValue(len(tickers))
        
        total_time = time.time() - start_time
        success_rate = (len([p for p in prices.values() if p > 0]) / len(tickers) * 100) if tickers else 0
        
        logger.info(f"✅ BATCH DOWNLOAD zakończony w {total_time:.2f}s")
        logger.info(f"   Sukces: {success_rate:.1f}% ({len([p for p in prices.values() if p > 0])}/{len(tickers)})")
        logger.info(f"   {self.price_cache.get_stats()}")
        
        return prices
    
    def update_exchange_rates_display(self):
        """Aktualizuje wyświetlane kursy walut USD/PLN, EUR/PLN, BTC/USD, ETH/USD i wartość SPX"""
        # Użyj już pobranych kursów
        usd_rate = self.current_usd_rate
        eur_rate = self.current_eur_rate
        btc_rate = self.current_btc_rate
        eth_rate = self.current_eth_rate
        spx_value = self.current_spx_value
        
        # Zaktualizuj labelki
        usd_label = self.findChild(QLabel, 'usd_rate_label')
        eur_label = self.findChild(QLabel, 'eur_rate_label')
        btc_label = self.findChild(QLabel, 'btc_rate_label')
        eth_label = self.findChild(QLabel, 'eth_rate_label')
        spx_label = self.findChild(QLabel, 'spx_value_label')
        
        if usd_label:
            if usd_rate:
                usd_label.setText(f'USD/PLN: {usd_rate:.4f}')
            else:
                usd_label.setText('USD/PLN: ---')
        
        if eur_label:
            if eur_rate:
                eur_label.setText(f'EUR/PLN: {eur_rate:.4f}')
            else:
                eur_label.setText('EUR/PLN: ---')
        
        if btc_label:
            if btc_rate:
                btc_label.setText(f'BTC: ${btc_rate:,.0f}')
            else:
                btc_label.setText('BTC: ---')
        
        if eth_label:
            if eth_rate:
                eth_label.setText(f'ETH: ${eth_rate:,.2f}')
            else:
                eth_label.setText('ETH: ---')
        
        if spx_label:
            if spx_value:
                spx_label.setText(f'SPX: {spx_value:,.2f}')
            else:
                spx_label.setText('SPX: ---')
    
    def fetch_and_cache_exchange_rates(self):
        """Pobiera kursy walut, BTC, ETH i SPX oraz zapisuje do cache z timestampem"""
        logger.info("Pobieranie kursów walut, BTC, ETH i SPX z Yahoo Finance...")
        self.current_usd_rate = self.fetch_exchange_rate('USDPLN=X')
        self.current_eur_rate = self.fetch_exchange_rate('EURPLN=X')
        self.current_btc_rate = self.fetch_exchange_rate('BTC-USD')
        self.current_eth_rate = self.fetch_exchange_rate('ETH-USD')
        self.current_spx_value = self.fetch_exchange_rate('^SPX')  # S&P 500
        self.exchange_rates_last_update = datetime.now()
        logger.info(f"Pobrano kursy: USD={self.current_usd_rate}, EUR={self.current_eur_rate}, BTC={self.current_btc_rate}, ETH={self.current_eth_rate}, SPX={self.current_spx_value}, timestamp={self.exchange_rates_last_update}")
        
        # Aktualizuj wyświetlanie po pobraniu
        self.update_exchange_rates_display()
    
    def fetch_exchange_rate(self, pair='USDPLN=X'):
        """Pobiera aktualny kurs waluty z Yahoo Finance"""
        try:
            stock = yf.Ticker(pair)
            info = stock.info
            
            # Sprawdź różne możliwe klucze dla ceny
            price_sources = [
                ('regularMarketPrice', info.get('regularMarketPrice')),
                ('currentPrice', info.get('currentPrice')),
                ('previousClose', info.get('previousClose')),
                ('bid', info.get('bid')),
                ('ask', info.get('ask'))
            ]
            
            for source_name, source_value in price_sources:
                if source_value:
                    rate = float(source_value)
                    logger.info(f"Pobrano kurs {pair}: {rate} (źródło: {source_name})")
                    return rate
            
            logger.warning(f"Nie znaleziono kursu dla {pair}")
            return None
            
        except Exception as e:
            logger.error(f"Błąd pobierania kursu {pair}: {str(e)}")
            return None
    
    def refresh_prices(self):
        """Odświeża ceny dla wszystkich pozycji i watchlisty - ZOPTYMALIZOWANA WERSJA"""
        logger.info("=" * 60)
        logger.info("Rozpoczęcie odświeżania cen z BATCH DOWNLOAD...")
        logger.info("=" * 60)
        
        self.progress_label.setText('Pobieranie danych...')
        QApplication.processEvents()
        
        start_time = time.time()
        
        logger.info("1. Odświeżam kursy walut...")
        self.progress_label.setText('Pobieranie danych...')
        QApplication.processEvents()
        self.fetch_and_cache_exchange_rates()
        
        all_tickers = set()
        
        for currency in ['USD', 'PLN']:
            positions = self.db.get_positions(currency)
            logger.info(f"   - {len(positions)} pozycji {currency}")
            for pos in positions:
                all_tickers.add(pos['ticker'])
            
            watchlist = self.db.get_watchlist(currency)
            logger.info(f"   - {len(watchlist)} pozycji w watchliście {currency}")
            for item in watchlist:
                all_tickers.add(item['ticker'])
        
        total_count = len(all_tickers)
        logger.info(f"2. Łącznie {total_count} unikalnych tickerów do odświeżenia")
        
        if all_tickers:
            logger.info("3. Czyszczenie cache przed odświeżeniem...")
            self.price_cache.clear()
            
            # Pokaż pasek postępu
            self.progress_bar.setVisible(True)
            self.progress_bar.setMaximum(total_count)
            self.progress_bar.setValue(0)
            self.progress_label.setText('Pobieranie danych...')
            QApplication.processEvents()
            
            logger.info("4. Wykonuję BATCH DOWNLOAD wszystkich cen...")
            prices = self.fetch_multiple_prices_batch_with_progress(list(all_tickers))
            
            success_count = len([p for p in prices.values() if p > 0])
            fail_count = len([p for p in prices.values() if p == 0])
            
            # Ukryj pasek postępu
            self.progress_bar.setVisible(False)
        else:
            logger.info("Brak tickerów do odświeżenia")
            success_count = 0
            fail_count = 0
        
        total_time = time.time() - start_time
        
        logger.info("=" * 60)
        logger.info(f"✅ ODŚWIEŻANIE ZAKOŃCZONE w {total_time:.2f}s")
        logger.info(f"   Sukces: {success_count}/{total_count} tickerów")
        logger.info(f"   Błędy: {fail_count}/{total_count} tickerów")
        if total_time > 0:
            logger.info(f"   Przyspieszenie: ~{total_count * 1.5 / total_time:.1f}x")
        logger.info("=" * 60)
        
        # Wymuś pełne odświeżenie (force_refresh=True)
        self.load_data(force_refresh=True)
        self.progress_label.setText('✅ Dane zaktualizowane')
    
    def load_data(self, force_refresh=False):
        """
        HYBRYDOWE ładowanie danych:
        1. Instant load z cache (nawet jeśli stary)
        2. Async refresh w tle jeśli potrzebny
        
        Args:
            force_refresh: Wymuś pełne odświeżenie (ignoruj cache)
        """
        logger.debug(f"load_data started (force_refresh={force_refresh}, currency={self.current_currency})")
        
        # Dla PLN sprawdź czy kursy są aktualne (cache 1 godzina)
        if self.current_currency == 'PLN':
            if (self.exchange_rates_last_update is None or 
                (datetime.now() - self.exchange_rates_last_update).total_seconds() > 3600):
                logger.info("Kursy walut wygasły lub nie są pobrane")
                
                # Jeśli kursy w ogóle nie są pobrane (None) - użyj domyślnych tymczasowo
                if self.current_usd_rate is None:
                    logger.warning("⚠️ Kursy nie są jeszcze pobrane - używam wartości domyślnych tymczasowo")
                    self.current_usd_rate = 4.0  # Domyślny kurs USD/PLN
                    self.current_eur_rate = 4.3  # Domyślny kurs EUR/PLN
                    # Pobierz w tle (nie blokuj UI)
                    import threading
                    def fetch_rates_bg():
                        self.fetch_and_cache_exchange_rates()
                    thread = threading.Thread(target=fetch_rates_bg, daemon=True)
                    thread.start()
                else:
                    # Kursy są już pobrane ale stare - odśwież (krótszy request bo cache yfinance)
                    self.fetch_and_cache_exchange_rates()
            else:
                logger.debug(f"Używam cache'owanych kursów (ostatnia aktualizacja: {self.exchange_rates_last_update})")
            self.update_exchange_rates_display()
        
        # Załaduj pozycje (hybrydowo)
        self.load_positions_hybrid(force_refresh)
        
        # Załaduj watchlist (hybrydowo - z cache + async refresh)
        self.load_watchlist_hybrid(force_refresh)
        self.load_history()
        
        # Załaduj strategie
        self.load_strategies_to_play()
        self.load_strategies_playing()
        
        logger.debug("Ładowanie danych zakończone")
    
    def load_positions_hybrid(self, force_refresh=False):
        """
        HYBRYDOWE ładowanie pozycji:
        1. INSTANT: Ładuj z cache (stare ceny jeśli są)
        2. Async refresh w tle jeśli cache stary
        """
        try:
            # KROK 1: Pobierz pozycje z cache
            positions_with_cache = self.db.get_positions_with_cache(self.current_currency)
            
            if not positions_with_cache:
                logger.info("Brak pozycji w portfolio")
                table = self.findChild(QTableWidget, f'positions_{self.current_currency}')
                if table:
                    table.setRowCount(0)
                return
            
            # Sprawdź czy jakiś cache jest stary (>60 min) lub brakuje
            needs_refresh = force_refresh
            if not needs_refresh:
                for pos in positions_with_cache:
                    cache_age = pos.get('cache_age_minutes')
                    if cache_age is None or cache_age > 60:
                        needs_refresh = True
                        break
            
            # KROK 2: Wyświetl dane z cache (INSTANT!)
            self.display_positions_from_cache(positions_with_cache)
            
            # KROK 3: Async refresh w tle (jeśli potrzebny)
            if needs_refresh and self.auto_refresh_enabled:
                if not self.positions_refresh_in_progress:
                    logger.info(f"Cache wymaga odświeżenia (force={force_refresh}) - startujemy async refresh")
                    self.start_async_price_refresh(positions_with_cache)
                else:
                    logger.debug("Refresh już w toku - pomijamy")
            else:
                logger.debug(f"Cache świeży - pomijamy refresh (needs_refresh={needs_refresh})")
                
        except Exception as e:
            logger.error(f"Błąd w load_positions_hybrid: {e}", exc_info=True)
            QMessageBox.critical(self, 'Błąd', f'Nie udało się załadować pozycji:\n{str(e)}')
    
    def display_positions_from_cache(self, positions):
        """Wyświetla pozycje używając cen z cache - INSTANT!"""
        logger.debug(f"Wyświetlanie {len(positions)} pozycji z cache")
        
        table = self.findChild(QTableWidget, f'positions_{self.current_currency}')
        if not table:
            logger.warning(f"Tabela positions_{self.current_currency} nie znaleziona!")
            return
        
        table.setRowCount(0)
        
        # Użyj już pobranych kursów
        current_usd_rate = self.current_usd_rate
        current_eur_rate = self.current_eur_rate
        
        total_profit = 0.0
        
        # Sortuj po tickerze (alfabetycznie)
        positions_sorted = sorted(positions, key=lambda x: x['ticker'])
        
        for pos in positions_sorted:
            # Dodaj aliasy dla kompatybilności z dialogami
            if 'purchase_price' in pos and 'buy_price' not in pos:
                pos['buy_price'] = pos['purchase_price']
            if 'purchase_date' in pos and 'buy_date' not in pos:
                pos['buy_date'] = pos['purchase_date']
            
            # DEBUG: Log usd_rate/eur_rate
            ticker = pos['ticker']
            logger.debug(f"{ticker}: usd_rate={pos.get('usd_rate')}, eur_rate={pos.get('eur_rate')}, currency={self.current_currency}")
            
            row = table.rowCount()
            table.insertRow(row)
            
            ticker = pos['ticker']
            quantity = pos['quantity']
            buy_price = pos['purchase_price']
            cached_price = pos.get('cached_price')
            cache_age = pos.get('cache_age_minutes')
            instrument_type = pos.get('instrument_type', 'Akcje')
            leverage = pos.get('leverage', 1)
            direction = pos.get('direction', 'Long')
            
            # Użyj cached price jeśli dostępny, inaczej pokazuj buy_price
            current_price = cached_price if cached_price is not None else buy_price
            
            # Ticker
            ticker_item = QTableWidgetItem(ticker)
            ticker_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 0, ticker_item)
            
            # Typ instrumentu
            type_item = QTableWidgetItem(instrument_type)
            type_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 1, type_item)
            
            # Cena zakupu
            buy_price_item = QTableWidgetItem(f"{buy_price:.2f}")
            buy_price_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 2, buy_price_item)
            
            # Cena aktualna (BEZ wskaźnika cache!)
            current_price_item = QTableWidgetItem(f"{current_price:.2f}")
            current_price_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 3, current_price_item)
            
            # Ilość
            quantity_item = QTableWidgetItem(f"{quantity:.2f}")
            quantity_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 4, quantity_item)
            
            # Depozyt/Wartość początkowa
            if instrument_type == 'CFD' and leverage and leverage > 0:
                value = (buy_price * quantity) / leverage
            else:
                value = buy_price * quantity
            
            if self.current_currency == 'PLN':
                if pos.get('usd_rate'):
                    value = value * pos['usd_rate']
                elif pos.get('eur_rate'):
                    value = value * pos['eur_rate']
            
            value_item = QTableWidgetItem(f"{value:.2f}")
            value_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 5, value_item)
            
            # Zysk/Strata - obliczenia IDENTYCZNE jak w starej wersji
            current_value = current_price * quantity
            buy_value = buy_price * quantity
            
            # Przelicz wartości na PLN jeśli pozycja ma zapisany kurs
            if self.current_currency == 'PLN':
                if pos.get('usd_rate'):
                    if current_usd_rate:
                        current_value = current_value * current_usd_rate
                    else:
                        current_value = current_value * pos.get('usd_rate')
                    buy_value = buy_value * pos.get('usd_rate')
                elif pos.get('eur_rate'):
                    if current_eur_rate:
                        current_value = current_value * current_eur_rate
                    else:
                        current_value = current_value * pos.get('eur_rate')
                    buy_value = buy_value * pos.get('eur_rate')
            
            # Oblicz zysk (BEZ pomnożenia przez leverage dla CFD!)
            if direction == 'Short':
                profit = buy_value - current_value
            else:
                profit = current_value - buy_value
            
            # Dodaj dywidendę
            dividend = pos.get('dividend', 0) or 0
            profit += dividend
            
            total_profit += profit
            
            profit_item = QTableWidgetItem(f"{profit:.2f}")
            profit_item.setForeground(QColor('green') if profit >= 0 else QColor('red'))
            profit_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 6, profit_item)
            
            # Procent zysku - obliczenia IDENTYCZNE jak w starej wersji
            if instrument_type == 'CFD' and leverage and leverage > 0:
                invested_capital = quantity * buy_price
                
                if self.current_currency == 'PLN':
                    if pos.get('usd_rate'):
                        invested_capital = invested_capital * pos['usd_rate']
                    elif pos.get('eur_rate'):
                        invested_capital = invested_capital * pos['eur_rate']
                
                invested_capital = invested_capital / leverage
            else:
                invested_capital = buy_price * quantity
                
                if self.current_currency == 'PLN':
                    if pos.get('usd_rate'):
                        invested_capital = invested_capital * pos['usd_rate']
                    elif pos.get('eur_rate'):
                        invested_capital = invested_capital * pos['eur_rate']
            
            if invested_capital > 0:
                profit_percent = (profit / invested_capital) * 100
            else:
                profit_percent = 0
            
            profit_percent_item = QTableWidgetItem(f"{profit_percent:.2f}%")
            profit_percent_item.setForeground(QColor('green') if profit_percent >= 0 else QColor('red'))
            profit_percent_item.setTextAlignment(Qt.AlignCenter)
            font = profit_percent_item.font()
            font.setBold(True)
            profit_percent_item.setFont(font)
            table.setItem(row, 7, profit_percent_item)
            
            # Alert (cel cenowy - tylko cena)
            alert_price = pos.get('alert_price')
            if alert_price:
                alert_text = f"{alert_price:.2f}"
            else:
                alert_text = '-'
            alert_item = QTableWidgetItem(alert_text)
            alert_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 8, alert_item)
            
            # Przyciski akcji - PRAWDZIWE GUZIKI!
            action_widget = QWidget()
            action_layout = QHBoxLayout()
            action_layout.setContentsMargins(2, 2, 2, 2)
            
            # Przycisk edytuj
            edit_button = QPushButton('Edytuj')
            edit_button.setStyleSheet('background-color: #3b82f6; color: white; padding: 5px;')
            edit_button.clicked.connect(lambda checked, p=pos: self.edit_position(p))
            action_layout.addWidget(edit_button)
            
            # Przycisk zamknij pozycję
            close_button = QPushButton('Zamknij pozycję')
            
            # Sprawdź alert
            has_alert = alert_price and current_price >= alert_price
            
            if has_alert:
                close_button.setStyleSheet(
                    'background-color: #10b981; color: white; font-weight: bold; padding: 5px;'
                )
                close_button.setText('✓ Zamknij')
                # Podświetl cały wiersz na zielono - alert osiągnięty
                for col in range(10):
                    item = table.item(row, col)
                    if item:
                        item.setBackground(QColor(220, 252, 231))
            elif profit > 0:
                # Podświetl na zielono pozycje zyskowne
                close_button.setStyleSheet(
                    'background-color: #9ca3af; color: white; padding: 5px;'
                )
                for col in range(10):
                    item = table.item(row, col)
                    if item:
                        item.setBackground(QColor(220, 252, 231))
            elif profit < 0:
                # Podświetl na czerwono pozycje na stracie
                close_button.setStyleSheet(
                    'background-color: #9ca3af; color: white; padding: 5px;'
                )
                for col in range(10):
                    item = table.item(row, col)
                    if item:
                        item.setBackground(QColor(255, 220, 220))
            else:
                close_button.setStyleSheet(
                    'background-color: #9ca3af; color: white; padding: 5px;'
                )
            
            close_button.clicked.connect(lambda checked, p=pos, cp=current_price: self.sell_position(p, cp))
            action_layout.addWidget(close_button)
            
            action_widget.setLayout(action_layout)
            table.setCellWidget(row, 9, action_widget)
        
        # Aktualizuj podsumowanie łącznego wyniku
        positions_profit_label = self.findChild(QLabel, f'positions_profit_{self.current_currency}')
        
        if positions_profit_label is not None:
            positions_profit_label.setText(f'{total_profit:.2f} {self.current_currency}')
            positions_profit_label.setStyleSheet(
                f'color: {"green" if total_profit >= 0 else "red"};'
            )
        
        logger.debug(f"Wyświetlono {len(positions_sorted)} pozycji z cache (total_profit={total_profit:.2f})")
    
    def start_async_price_refresh(self, positions):
        """Startuje asynchroniczne odświeżanie cen w tle - nie blokuje UI!"""
        self.positions_refresh_in_progress = True
        self.progress_label.setText("⏳ Pobieranie danych...")
        
        # Uruchom w osobnym wątku
        refresh_thread = threading.Thread(
            target=self._refresh_prices_background,
            args=(positions,),
            daemon=True
        )
        refresh_thread.start()
    
    def _refresh_prices_background(self, positions):
        """Wykonywane w tle - pobiera świeże ceny i aktualizuje cache + UI"""
        try:
            logger.info("🔄 Background refresh rozpoczęty")
            start_time = datetime.now()
            
            # Przygotuj listę tickerów do odświeżenia
            tickers_to_refresh = []
            for pos in positions:
                cache_age = pos.get('cache_age_minutes')
                if cache_age is None or cache_age > 60:
                    tickers_to_refresh.append(pos['ticker'])
            
            if not tickers_to_refresh:
                logger.info("Wszystkie ceny są świeże - koniec refresh")
                self.positions_refresh_in_progress = False
                return
            
            logger.info(f"Odświeżanie {len(tickers_to_refresh)} tickerów: {tickers_to_refresh}")
            
            # Pobierz świeże ceny (batch)
            fresh_prices = self.fetch_multiple_prices_batch(tickers_to_refresh)
            
            # Aktualizuj cache w bazie
            cache_updates = []
            for ticker in tickers_to_refresh:
                price_data = fresh_prices.get(ticker)
                if price_data and price_data > 0:
                    # fetch_multiple_prices_batch zwraca dict {ticker: price} lub {ticker: price_data}
                    price = price_data if isinstance(price_data, (int, float)) else price_data.get('price', 0)
                    if price > 0:
                        cache_updates.append({
                            'ticker': ticker,
                            'price': price,
                            'company_name': None,  # Możesz dodać company_name z yfinance jeśli chcesz
                            'currency': self.current_currency
                        })
            
            if cache_updates:
                self.db.update_price_cache_batch(cache_updates)
                logger.info(f"✅ Zaktualizowano cache dla {len(cache_updates)} tickerów")
            
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"🔄 Background refresh zakończony w {elapsed:.2f}s")
            
            # Zaplanuj UI update w głównym wątku
            self.schedule_ui_refresh()
            
        except Exception as e:
            logger.error(f"Błąd w background refresh: {e}", exc_info=True)
        finally:
            self.positions_refresh_in_progress = False
            self.last_refresh_time = datetime.now()
    
    def schedule_ui_refresh(self):
        """Thread-safe: Odświeża UI w głównym wątku Qt"""
        QTimer.singleShot(0, self._ui_refresh_after_background)
    
    def _ui_refresh_after_background(self):
        """Odświeża UI po background refresh"""
        try:
            # Przeładuj dane (teraz z fresh cache)
            positions_with_cache = self.db.get_positions_with_cache(self.current_currency)
            self.display_positions_from_cache(positions_with_cache)
            
            # Ustaw status tylko jeśli watchlist też się skończył
            if not self.watchlist_refresh_in_progress:
                self.progress_label.setText("✅ Dane zaktualizowane")
                # Resetuj status po 2 sekundach
                QTimer.singleShot(2000, self._set_ready_if_idle)
            
        except Exception as e:
            logger.error(f"Błąd w UI refresh: {e}", exc_info=True)
    
    def _set_ready_if_idle(self):
        """Ustawia status 'Gotowy' tylko jeśli żaden refresh nie jest w toku"""
        if not self.positions_refresh_in_progress and not self.watchlist_refresh_in_progress:
            self.progress_label.setText("Gotowy")
    
    def load_positions(self):
        """Ładuje aktualne pozycje"""
        logger.debug(f"Ładowanie pozycji dla waluty: {self.current_currency}")
        
        try:
            positions = self.db.get_positions(self.current_currency)
            logger.info(f"Załadowano {len(positions)} pozycji")
            
            table = self.findChild(QTableWidget, f'positions_{self.current_currency}')
            
            # Sprawdź czy tabela istnieje
            if table is None:
                logger.warning(f"Tabela positions_{self.current_currency} nie znaleziona!")
                return
            
            table.setRowCount(0)
            
            # OPTYMALIZACJA: BATCH DOWNLOAD wszystkich cen naraz!
            tickers = [pos['ticker'] for pos in positions]
            prices = self.fetch_multiple_prices_batch(tickers)
            
            # Użyj już pobranych kursów z self
            current_usd_rate = self.current_usd_rate
            current_eur_rate = self.current_eur_rate
            
            total_profit = 0.0  # Zmienna do sumowania zysków/strat
            
            for pos in positions:
                row = table.rowCount()
                table.insertRow(row)
                
                # OPTYMALIZACJA: Usunięto kolumnę "Nazwa spółki" - wyświetlamy tylko ticker (15x szybciej!)
                # Ticker (indeks kolumny zmieniony z 1 na 0)
                ticker_item = QTableWidgetItem(pos['ticker'])
                ticker_item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, 0, ticker_item)
                
                # Typ instrumentu (indeks kolumny zmieniony z 2 na 1)
                instrument_type = pos.get('instrument_type', 'Akcje')
                type_item = QTableWidgetItem(instrument_type)
                type_item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, 1, type_item)
                
                # Cena zakupu (indeks kolumny zmieniony z 3 na 2)
                buy_price_item = QTableWidgetItem(f"{pos['buy_price']:.2f}")
                buy_price_item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, 2, buy_price_item)
                
                # OPTYMALIZACJA: Użyj już pobranej ceny (bez dodatkowego API call!)
                current_price = prices.get(pos['ticker'], 0.0)
                
                # Cena aktualna (indeks kolumny zmieniony z 4 na 3)
                current_price_item = QTableWidgetItem(f"{current_price:.2f}")
                current_price_item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, 3, current_price_item)
                
                # Ilość (indeks kolumny zmieniony z 5 na 4)
                quantity_item = QTableWidgetItem(f"{pos['quantity']:.2f}")
                quantity_item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, 4, quantity_item)
                
                # Depozyt/Wartość początkowa - pokazuje ile kapitału zainwestowałeś
                leverage = pos.get('leverage', 1)
                direction = pos.get('direction', 'Long')
                
                if instrument_type == 'CFD' and leverage and leverage > 0:
                    # Dla CFD: depozyt = (buy_price * quantity * kurs_zakupu) / leverage
                    value = (pos['buy_price'] * pos['quantity']) / leverage
                else:
                    # Dla akcji: ile zapłaciłeś = buy_price * quantity * kurs_zakupu
                    value = pos['buy_price'] * pos['quantity']
                
                # Przelicz przez kurs ZAKUPU jeśli pozycja ma zapisany usd_rate lub eur_rate
                if self.current_currency == 'PLN':
                    # Sprawdź czy pozycja ma zapisany kurs USD (oznacza że instrument jest w USD)
                    if pos.get('usd_rate'):
                        value = value * pos['usd_rate']
                    # Sprawdź czy pozycja ma zapisany kurs EUR (oznacza że instrument jest w EUR)
                    elif pos.get('eur_rate'):
                        value = value * pos['eur_rate']
                    
                value_item = QTableWidgetItem(f"{value:.2f}")
                value_item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, 5, value_item)
                
                # Zysk/Strata - obliczamy jako różnicę wartości: (ilość * cena_aktualna * kurs_aktualny) - (ilość * cena_zakupu * kurs_zakupu)
                leverage = pos.get('leverage', 1)
                direction = pos.get('direction', 'Long')
                
                # Obliczenie wartości aktualnej i wartości zakupu
                # Wartość aktualna w walucie instrumentu
                current_value = current_price * pos['quantity']
                # Wartość zakupu w walucie instrumentu
                buy_value = pos['buy_price'] * pos['quantity']
                
                # Przelicz wartości na PLN jeśli pozycja ma zapisany kurs
                if self.current_currency == 'PLN':
                    if pos.get('usd_rate'):
                        # Wartość aktualna przelicz przez obecny kurs USD
                        if current_usd_rate:
                            current_value = current_value * current_usd_rate
                        else:
                            current_value = current_value * pos.get('usd_rate')
                        # Wartość zakupu przelicz przez kurs zakupu
                        buy_value = buy_value * pos.get('usd_rate')
                    elif pos.get('eur_rate'):
                        # Wartość aktualna przelicz przez obecny kurs EUR
                        if current_eur_rate:
                            current_value = current_value * current_eur_rate
                        else:
                            current_value = current_value * pos.get('eur_rate')
                        # Wartość zakupu przelicz przez kurs zakupu
                        buy_value = buy_value * pos.get('eur_rate')
                
                # Oblicz zysk jako różnicę wartości
                if direction == 'Short':
                    # Dla short zarabiamy gdy cena spada
                    profit = buy_value - current_value
                else:
                    # Dla long zarabiamy gdy cena rośnie
                    profit = current_value - buy_value
                
                # Dodaj dywidendę do zysku
                dividend = pos.get('dividend', 0) or 0
                profit += dividend
                
                # Dodaj do łącznego wyniku
                total_profit += profit
                    
                profit_item = QTableWidgetItem(f"{profit:.2f}")
                profit_item.setForeground(QColor('green') if profit >= 0 else QColor('red'))
                profit_item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, 6, profit_item)
                
                # Procent zysku
                if instrument_type == 'CFD' and leverage and leverage > 0:
                    # Dla CFD: depozyt = (quantity * buy_price * kurs_zakupu) / leverage
                    # Najpierw oblicz wartość pozycji
                    invested_capital = pos['quantity'] * pos['buy_price']
                    
                    # Pomnóż przez kurs zakupu (jeśli PLN)
                    if self.current_currency == 'PLN':
                        if pos.get('usd_rate'):
                            invested_capital = invested_capital * pos['usd_rate']
                        elif pos.get('eur_rate'):
                            invested_capital = invested_capital * pos['eur_rate']
                    
                    # Podziel przez leverage (to jest depozyt, margin requirement)
                    invested_capital = invested_capital / leverage
                else:
                    # Dla akcji: kapitał zainwestowany = buy_price * quantity * kurs_zakupu
                    invested_capital = pos['buy_price'] * pos['quantity']
                    
                    # Dla PLN - przelicz kapitał przez kurs zakupu
                    if self.current_currency == 'PLN':
                        if pos.get('usd_rate'):
                            invested_capital = invested_capital * pos['usd_rate']
                        elif pos.get('eur_rate'):
                            invested_capital = invested_capital * pos['eur_rate']
                
                if invested_capital > 0:
                    profit_percent = (profit / invested_capital) * 100
                else:
                    profit_percent = 0
                
                profit_percent_item = QTableWidgetItem(f"{profit_percent:.2f}%")
                profit_percent_item.setForeground(QColor('green') if profit_percent >= 0 else QColor('red'))
                profit_percent_item.setTextAlignment(Qt.AlignCenter)
                # Dodaj pogrubienie dla czytelności
                font = profit_percent_item.font()
                font.setBold(True)
                profit_percent_item.setFont(font)
                table.setItem(row, 7, profit_percent_item)
                
                # Alert (cel cenowy - tylko cena)
                if pos['alert_price']:
                    alert_text = f"{pos['alert_price']:.2f}"
                else:
                    alert_text = '-'
                alert_item = QTableWidgetItem(alert_text)
                alert_item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, 8, alert_item)
                
                # Przyciski akcji
                action_widget = QWidget()
                action_layout = QHBoxLayout()
                action_layout.setContentsMargins(2, 2, 2, 2)
                
                # Przycisk edytuj
                edit_button = QPushButton('Edytuj')
                edit_button.setStyleSheet('background-color: #3b82f6; color: white; padding: 5px;')
                edit_button.clicked.connect(lambda checked, p=pos: self.edit_position(p))
                action_layout.addWidget(edit_button)
                
                # Przycisk zamknij pozycję
                close_button = QPushButton('Zamknij pozycję')
                
                # Sprawdź alert
                has_alert = pos['alert_price'] and current_price >= pos['alert_price']
                
                if has_alert:
                    close_button.setStyleSheet(
                        'background-color: #10b981; color: white; font-weight: bold; padding: 5px;'
                    )
                    close_button.setText('✓ Zamknij')
                    # Podświetl cały wiersz na zielono - alert osiągnięty (teraz mamy 10 kolumn: 0-9)
                    for col in range(10):
                        item = table.item(row, col)
                        if item:
                            item.setBackground(QColor(220, 252, 231))
                elif profit > 0:
                    # Podświetl na zielono pozycje zyskowne (delikatniej niż alert)
                    close_button.setStyleSheet(
                        'background-color: #9ca3af; color: white; padding: 5px;'
                    )
                    for col in range(10):
                        item = table.item(row, col)
                        if item:
                            item.setBackground(QColor(220, 252, 231))
                elif profit < 0:
                    # Podświetl na czerwono pozycje na stracie
                    close_button.setStyleSheet(
                        'background-color: #9ca3af; color: white; padding: 5px;'
                    )
                    for col in range(10):
                        item = table.item(row, col)
                        if item:
                            item.setBackground(QColor(255, 220, 220))
                else:
                    close_button.setStyleSheet(
                        'background-color: #9ca3af; color: white; padding: 5px;'
                    )
                
                close_button.clicked.connect(lambda checked, p=pos, cp=current_price: self.sell_position(p, cp))
                action_layout.addWidget(close_button)
                
                action_widget.setLayout(action_layout)
                table.setCellWidget(row, 9, action_widget)
            
            # Aktualizuj podsumowanie łącznego wyniku dla pozycji
            positions_profit_label = self.findChild(QLabel, f'positions_profit_{self.current_currency}')
            
            if positions_profit_label is not None:
                positions_profit_label.setText(f'{total_profit:.2f} {self.current_currency}')
                positions_profit_label.setStyleSheet(
                    f'color: {"green" if total_profit >= 0 else "red"};'
                )
        
        except Exception as e:
            logger.error(f"Błąd w load_positions: {type(e).__name__} - {str(e)}")
            logger.exception("Szczegóły błędu:")
            QMessageBox.critical(self, 'Błąd', 
                f'Wystąpił błąd podczas ładowania pozycji:\n{str(e)}\n\n'
                f'Sprawdź logi w folderze Logs/')
    
    def load_history(self):
        """Ładuje historię transakcji"""
        try:
            history = self.db.get_history(self.current_currency)
            
            table = self.findChild(QTableWidget, f'history_{self.current_currency}')
            
            # Sprawdź czy tabela istnieje
            if table is None:
                return
            
            table.setRowCount(0)
            
            for h in history:
                row = table.rowCount()
                table.insertRow(row)
                
                ticker_item = QTableWidgetItem(h['ticker'])
                ticker_item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, 0, ticker_item)
                
                buy_price_item = QTableWidgetItem(f"{h['buy_price']:.2f}")
                buy_price_item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, 1, buy_price_item)
                
                sell_price_item = QTableWidgetItem(f"{h['sell_price']:.2f}")
                sell_price_item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, 2, sell_price_item)
                
                quantity_item = QTableWidgetItem(f"{h['quantity']:.2f}")
                quantity_item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, 3, quantity_item)
                
                profit_item = QTableWidgetItem(f"{h['profit']:.2f}")
                profit_item.setForeground(QColor('green') if h['profit'] >= 0 else QColor('red'))
                profit_item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, 4, profit_item)
                
                # SWAP - koszt SWAP (tylko dla CFD)
                swap_cost = h.get('swap_cost', 0) or 0
                swap_text = f"{swap_cost:.2f}" if swap_cost > 0 else '-'
                swap_item = QTableWidgetItem(swap_text)
                swap_item.setTextAlignment(Qt.AlignCenter)
                if swap_cost > 0:
                    swap_item.setForeground(QColor('red'))
                table.setItem(row, 5, swap_item)
                
                # Dywidenda
                dividend = h.get('dividend', 0) or 0
                dividend_text = f"{dividend:.2f}" if dividend > 0 else '-'
                dividend_item = QTableWidgetItem(dividend_text)
                dividend_item.setTextAlignment(Qt.AlignCenter)
                if dividend > 0:
                    dividend_item.setForeground(QColor('#10b981'))  # Zielony dla dywidendy
                    # Dodaj pogrubienie
                    font = dividend_item.font()
                    font.setBold(True)
                    dividend_item.setFont(font)
                table.setItem(row, 6, dividend_item)
                
                # Procent zysku
                instrument_type = h.get('instrument_type', 'Akcje')
                leverage = h.get('leverage', 1)
                
                if instrument_type == 'CFD' and leverage and leverage > 0:
                    # Dla CFD: depozyt = (quantity * buy_price * kurs_zakupu) / leverage
                    invested_capital = h['quantity'] * h['buy_price']
                    
                    # Pomnóż przez kurs zakupu (jeśli pozycja ma zapisany kurs)
                    if self.current_currency == 'PLN':
                        if h.get('usd_rate'):
                            invested_capital = invested_capital * h['usd_rate']
                        elif h.get('eur_rate'):
                            invested_capital = invested_capital * h['eur_rate']
                    
                    # Podziel przez leverage
                    invested_capital = invested_capital / leverage
                else:
                    # Dla akcji: kapitał zainwestowany = buy_price * quantity * kurs_zakupu
                    invested_capital = h['buy_price'] * h['quantity']
                    
                    # Dla PLN - przelicz kapitał przez kurs zakupu
                    if self.current_currency == 'PLN':
                        if h.get('usd_rate'):
                            invested_capital = invested_capital * h['usd_rate']
                        elif h.get('eur_rate'):
                            invested_capital = invested_capital * h['eur_rate']
                
                if invested_capital > 0:
                    profit_percent = (h['profit'] / invested_capital) * 100
                else:
                    profit_percent = 0
                
                profit_percent_item = QTableWidgetItem(f"{profit_percent:.2f}%")
                profit_percent_item.setForeground(QColor('green') if profit_percent >= 0 else QColor('red'))
                profit_percent_item.setTextAlignment(Qt.AlignCenter)
                # Dodaj pogrubienie dla czytelności
                font = profit_percent_item.font()
                font.setBold(True)
                profit_percent_item.setFont(font)
                table.setItem(row, 7, profit_percent_item)
                
                buy_date = datetime.fromisoformat(h['buy_date']).strftime('%Y-%m-%d')
                sell_date = datetime.fromisoformat(h['sell_date']).strftime('%Y-%m-%d')
                
                buy_date_item = QTableWidgetItem(buy_date)
                buy_date_item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, 8, buy_date_item)
                
                sell_date_item = QTableWidgetItem(sell_date)
                sell_date_item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, 9, sell_date_item)
                
                # Przycisk edytuj
                edit_button = QPushButton('Edytuj')
                edit_button.setStyleSheet('background-color: #3b82f6; color: white; padding: 5px;')
                edit_button.clicked.connect(lambda checked, h=h: self.edit_history(h))
                table.setCellWidget(row, 10, edit_button)
            
            # Aktualizuj podsumowanie
            total_profit = self.db.get_total_profit(self.current_currency)
            profit_label = self.findChild(QLabel, f'profit_{self.current_currency}')
            
            # Sprawdź czy label istnieje
            if profit_label is None:
                return
            
            profit_label.setText(f'{total_profit:.2f} {self.current_currency}')
            profit_label.setStyleSheet(
                f'color: {"green" if total_profit >= 0 else "red"};'
            )
        
        except Exception as e:
            logger.error(f"Błąd w load_history: {type(e).__name__} - {str(e)}")
            logger.exception("Szczegóły błędu:")
            QMessageBox.critical(self, 'Błąd', 
                f'Wystąpił błąd podczas ładowania historii:\n{str(e)}\n\n'
                f'Sprawdź logi w folderze Logs/')
    
    def export_positions(self, currency):
        """Eksportuje pozycje do pliku CSV"""
        try:
            positions = self.db.get_positions(currency)
            
            if not positions:
                QMessageBox.information(self, 'Eksport', 'Brak pozycji do eksportu.')
                return
            
            # Otwórz dialog do wyboru pliku
            default_name = f'pozycje_{currency}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            file_path, _ = QFileDialog.getSaveFileName(
                self, 
                'Eksportuj pozycje', 
                default_name,
                'CSV Files (*.csv)'
            )
            
            if not file_path:
                return
            
            # Waliduj ścieżkę
            try:
                safe_path = safe_file_path(file_path)
            except ValueError as e:
                QMessageBox.critical(self, 'Błąd', f'Nieprawidłowa ścieżka: {str(e)}')
                return
            
            # Zapisz do CSV
            with open(safe_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                # Nagłówki
                writer.writerow(['ticker', 'currency', 'buy_price', 'quantity', 'purchase_date', 'usd_rate', 'alert_price', 'instrument_type', 'leverage', 'direction'])
                
                # Dane
                for pos in positions:
                    writer.writerow([
                        pos['ticker'],
                        pos['currency'],
                        pos.get('buy_price', pos.get('purchase_price', '')),  # Obsługa obu nazw
                        pos['quantity'],
                        pos.get('purchase_date', pos.get('buy_date', '')),  # Obsługa obu nazw
                        pos.get('usd_rate', ''),
                        pos.get('alert_price', ''),
                        pos.get('instrument_type', 'Akcje'),
                        pos.get('leverage', ''),
                        pos.get('direction', 'Long')
                    ])
            
            logger.info(f"Wyeksportowano {len(positions)} pozycji do {safe_path}")
            QMessageBox.information(self, 'Eksport', f'Wyeksportowano {len(positions)} pozycji do:\n{safe_path}')
            
        except Exception as e:
            logger.error(f"Błąd eksportu pozycji: {type(e).__name__} - {str(e)}")
            logger.exception("Szczegóły błędu:")
            QMessageBox.critical(self, 'Błąd', f'Błąd eksportu:\n{str(e)}')
    
    def import_positions(self, currency):
        """Importuje pozycje z pliku CSV"""
        try:
            # Otwórz dialog do wyboru pliku
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                'Importuj pozycje',
                '',
                'CSV Files (*.csv)'
            )
            
            if not file_path:
                return
            
            # Waliduj ścieżkę
            try:
                safe_path = safe_file_path(file_path)
            except ValueError as e:
                QMessageBox.critical(self, 'Błąd', f'Nieprawidłowa ścieżka: {str(e)}')
                return
            
            # Wczytaj CSV
            imported_count = 0
            errors = []
            
            with open(safe_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                for row_num, row in enumerate(reader, start=2):
                    try:
                        # Sanityzacja i walidacja
                        ticker = sanitize_ticker(row['ticker'])
                        buy_price = safe_float_convert(row['buy_price'], "cena zakupu")
                        quantity = safe_float_convert(row['quantity'], "ilość")
                        buy_date = row['buy_date'].strip() if row['buy_date'].strip() else datetime.now().strftime('%Y-%m-%d')
                        
                        usd_rate = None
                        if row.get('usd_rate') and row['usd_rate'].strip():
                            usd_rate = safe_float_convert(row['usd_rate'], "kurs USD")
                        
                        eur_rate = None
                        if row.get('eur_rate') and row['eur_rate'].strip():
                            eur_rate = safe_float_convert(row['eur_rate'], "kurs EUR")
                        
                        alert_price = None
                        if row.get('alert_price') and row['alert_price'].strip():
                            alert_price = safe_float_convert(row['alert_price'], "cena alertu")
                        
                        dividend = None
                        if row.get('dividend') and row['dividend'].strip():
                            dividend = float(row['dividend'])
                            if dividend < 0:
                                dividend = None
                        
                        # Obsługa instrument_type, leverage i direction (opcjonalne w CSV)
                        instrument_type = row.get('instrument_type', 'Akcje')
                        if instrument_type not in ('Akcje', 'CFD'):
                            instrument_type = 'Akcje'
                        
                        leverage = None
                        direction = 'Long'
                        swap_daily = None
                        if instrument_type == 'CFD':
                            if row.get('leverage') and row['leverage'].strip():
                                leverage = safe_float_convert(row['leverage'], "dźwignia")
                            if row.get('direction') and row['direction'].strip():
                                direction = row['direction'] if row['direction'] in ('Long', 'Short') else 'Long'
                            if row.get('swap_daily') and row['swap_daily'].strip():
                                swap_daily = float(row['swap_daily'])
                                if swap_daily < 0:
                                    swap_daily = None
                        
                        # Dodaj do bazy
                        self.db.add_position(
                            ticker=ticker,
                            currency=currency,
                            buy_price=buy_price,
                            quantity=quantity,
                            purchase_date=buy_date,
                            usd_rate=usd_rate,
                            eur_rate=eur_rate,
                            alert_price=alert_price,
                            instrument_type=instrument_type,
                            leverage=leverage,
                            direction=direction,
                            swap_daily=swap_daily,
                            dividend=dividend
                        )
                        
                        imported_count += 1
                        
                    except (ValueError, KeyError) as e:
                        error_msg = f"Wiersz {row_num}: {str(e)}"
                        errors.append(error_msg)
                        logger.warning(f"Błąd importu wiersza {row_num}: {str(e)}")
            
            # Odśwież widok
            self.load_data()
            
            # Pokaż wynik
            message = f'Zaimportowano {imported_count} pozycji'
            if errors:
                message += f'\n\nBłędy ({len(errors)}):\n' + '\n'.join(errors[:5])
                if len(errors) > 5:
                    message += f'\n... i {len(errors)-5} więcej'
            
            logger.info(f"Import zakończony: {imported_count} sukces, {len(errors)} błędów")
            
            if errors:
                QMessageBox.warning(self, 'Import', message)
            else:
                QMessageBox.information(self, 'Import', message)
            
        except Exception as e:
            logger.error(f"Błąd importu pozycji: {type(e).__name__} - {str(e)}")
            logger.exception("Szczegóły błędu:")
            QMessageBox.critical(self, 'Błąd', f'Błąd importu:\n{str(e)}')
    
    def export_history(self, currency):
        """Eksportuje historię do pliku CSV"""
        try:
            history = self.db.get_history(currency)
            
            if not history:
                QMessageBox.information(self, 'Eksport', 'Brak historii do eksportu.')
                return
            
            # Otwórz dialog do wyboru pliku
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                'Eksportuj historię',
                f'historia_{currency}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv',
                'CSV Files (*.csv)'
            )
            
            if not file_path:
                return
            
            # Zapisz do CSV
            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                # Nagłówki
                writer.writerow(['ticker', 'currency', 'buy_price', 'sell_price', 'quantity', 
                               'profit', 'buy_date', 'sell_date', 'usd_rate', 'instrument_type', 'leverage', 'direction'])
                
                # Dane
                for h in history:
                    writer.writerow([
                        h['ticker'],
                        h['currency'],
                        h['buy_price'],
                        h['sell_price'],
                        h['quantity'],
                        h['profit'],
                        h['buy_date'],
                        h['sell_date'],
                        h.get('usd_rate', ''),
                        h.get('instrument_type', 'Akcje'),
                        h.get('leverage', ''),
                        h.get('direction', 'Long')
                    ])
            
            logger.info(f"Wyeksportowano {len(history)} transakcji do {file_path}")
            QMessageBox.information(self, 'Eksport', f'Wyeksportowano {len(history)} transakcji do:\n{file_path}')
            
        except Exception as e:
            logger.error(f"Błąd eksportu historii: {type(e).__name__} - {str(e)}")
            logger.exception("Szczegóły błędu:")
            QMessageBox.critical(self, 'Błąd', f'Błąd eksportu:\n{str(e)}')
    
    def import_history(self, currency):
        """Importuje historię z pliku CSV"""
        try:
            # Otwórz dialog do wyboru pliku
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                'Importuj historię',
                '',
                'CSV Files (*.csv)'
            )
            
            if not file_path:
                return
            
            # Wczytaj CSV
            imported_count = 0
            errors = []
            
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                for row_num, row in enumerate(reader, start=2):
                    try:
                        ticker = row['ticker'].strip().upper()
                        buy_price = float(row['buy_price'])
                        sell_price = float(row['sell_price'])
                        quantity = float(row['quantity'])
                        profit = float(row['profit'])
                        buy_date = row['buy_date'].strip()
                        sell_date = row['sell_date'].strip()
                        
                        usd_rate = None
                        if row.get('usd_rate') and row['usd_rate'].strip():
                            usd_rate = float(row['usd_rate'])
                        
                        # Obsługa instrument_type, leverage i direction (opcjonalne w CSV)
                        instrument_type = row.get('instrument_type', 'Akcje')
                        if instrument_type not in ('Akcje', 'CFD'):
                            instrument_type = 'Akcje'
                        
                        leverage = None
                        direction = 'Long'
                        if instrument_type == 'CFD':
                            if row.get('leverage') and row['leverage'].strip():
                                leverage = float(row['leverage'])
                            if row.get('direction') and row['direction'].strip():
                                direction = row['direction'] if row['direction'] in ('Long', 'Short') else 'Long'
                        
                        # Dodaj do bazy
                        self.db.add_to_history(
                            ticker=ticker,
                            currency=currency,
                            buy_price=buy_price,
                            sell_price=sell_price,
                            quantity=quantity,
                            profit=profit,
                            buy_date=buy_date,
                            sell_date=sell_date,
                            usd_rate=usd_rate,
                            instrument_type=instrument_type,
                            leverage=leverage,
                            direction=direction
                        )
                        
                        imported_count += 1
                        
                    except Exception as e:
                        error_msg = f"Wiersz {row_num}: {str(e)}"
                        errors.append(error_msg)
                        logger.warning(f"Błąd importu wiersza {row_num}: {str(e)}")
            
            # Odśwież widok
            self.load_data()
            
            # Pokaż wynik
            message = f'Zaimportowano {imported_count} transakcji'
            if errors:
                message += f'\n\nBłędy ({len(errors)}):\n' + '\n'.join(errors[:5])
                if len(errors) > 5:
                    message += f'\n... i {len(errors)-5} więcej'
            
            logger.info(f"Import historii zakończony: {imported_count} sukces, {len(errors)} błędów")
            
            if errors:
                QMessageBox.warning(self, 'Import', message)
            else:
                QMessageBox.information(self, 'Import', message)
            
        except Exception as e:
            logger.error(f"Błąd importu historii: {type(e).__name__} - {str(e)}")
            logger.exception("Szczegóły błędu:")
            QMessageBox.critical(self, 'Błąd', f'Błąd importu:\n{str(e)}')
    
    def add_to_watchlist(self, currency, prefill_data=None):
        """Dodaje spółkę do watchlisty"""
        logger.info(f"Otwieranie okna dodawania do watchlisty dla waluty: {currency}")
        
        try:
            dialog = AddWatchlistDialog(currency, self, prefill_data=prefill_data)
            if dialog.exec_() == QDialog.Accepted:
                data = dialog.watchlist_data
                
                logger.info(f"Dodawanie do watchlisty: {data}")
                
                # Pobierz aktualną cenę aby sprawdzić ticker
                self.progress_label.setText('Sprawdzam ticker...')
                QApplication.processEvents()
                
                logger.info(f"Pobieranie ceny dla tickera: {data['ticker']}")
                price = self.fetch_price(data['ticker'])
                
                if price is None:
                    logger.warning(f"Nie udało się pobrać ceny dla {data['ticker']}")
                    
                    # Pokaż komunikat z pytaniem czy użytkownik chce poprawić dane
                    reply = QMessageBox.warning(self, 'Błąd', 
                        f'Nie udało się pobrać ceny dla {data["ticker"]}.\n'
                        'Sprawdź ticker (np. AAPL, PKO.WA)\n\n'
                        'Szczegóły w pliku Logs/Log_*.txt\n\n'
                        'Czy chcesz poprawić ticker i spróbować ponownie?',
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.Yes)
                    
                    self.progress_label.setText('Gotowy')
                    
                    # Jeśli użytkownik chce poprawić, wywołaj ponownie okno z danymi
                    if reply == QMessageBox.Yes:
                        self.add_to_watchlist(currency, prefill_data=data)
                    
                    return
                
                logger.info(f"Cena pobrana pomyślnie: {price}")
                
                # Dodaj do bazy
                watchlist_id = self.db.add_to_watchlist(
                    ticker=data['ticker'],
                    currency=currency,
                    hp1=data['hp1'],
                    hp2=data['hp2'],
                    hp3=data['hp3'],
                    hp4=data['hp4'],
                    note=data.get('note')
                )
                
                logger.warning(f"Dodano do watchlisty z ID: {watchlist_id}")
                
                self.progress_label.setText(f'Dodano {data["ticker"]} do obserwowanych')
                self.load_data()
        
        except Exception as e:
            logger.error(f"Błąd w add_to_watchlist: {type(e).__name__} - {str(e)}")
            logger.exception("Szczegóły błędu:")
            QMessageBox.critical(self, 'Błąd', 
                f'Wystąpił błąd podczas dodawania do obserwowanych:\n{str(e)}\n\n'
                f'Sprawdź logi w folderze Logs/')
            self.progress_label.setText('Błąd')
    
    def load_watchlist(self):
        """Ładuje watchlistę"""
        logger.debug(f"Ładowanie watchlisty dla waluty: {self.current_currency}")
        
        try:
            watchlist = self.db.get_watchlist(self.current_currency)
            logger.info(f"Załadowano {len(watchlist)} pozycji z watchlisty")
            
            table = self.findChild(QTableWidget, f'watchlist_{self.current_currency}')
            
            if table is None:
                logger.warning(f"Tabela watchlist_{self.current_currency} nie znaleziona!")
                return
            
            table.setRowCount(0)
            
            # OPTYMALIZACJA: BATCH DOWNLOAD wszystkich cen naraz!
            tickers = [item['ticker'] for item in watchlist]
            prices = self.fetch_multiple_prices_batch(tickers) if tickers else {}
            
            # Lista alertów do wyświetlenia
            alerts = []
            
            for item in watchlist:
                row = table.rowCount()
                table.insertRow(row)
                
                # OPTYMALIZACJA: Usunięto kolumnę "Nazwa spółki" - wyświetlamy tylko ticker
                # Ticker (indeks kolumny zmieniony z 1 na 0)
                ticker_item = QTableWidgetItem(item['ticker'])
                ticker_item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, 0, ticker_item)
                
                # OPTYMALIZACJA: Użyj już pobranej ceny!
                current_price = prices.get(item['ticker'], 0.0)
                
                # Cena aktualna (indeks kolumny zmieniony z 2 na 1)
                current_price_item = QTableWidgetItem(f"{current_price:.2f}")
                current_price_item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, 1, current_price_item)
                
                # Sprawdź które poziomy zostały osiągnięte (SPADKI - cena <= HP)
                # Sekwencyjnie: HP2 tylko jeśli HP1 triggered, HP3 tylko jeśli HP2 triggered, itd.
                alert_triggered = False
                triggered_levels = []
                newly_triggered = {}
                
                # HP1 - może być wyzwolony zawsze (indeks kolumny zmieniony z 3 na 2)
                hp1_text = f"{item['hp1']:.2f}" if item['hp1'] else '-'
                hp1_item = QTableWidgetItem(hp1_text)
                hp1_item.setTextAlignment(Qt.AlignCenter)
                hp1_active = False
                if item['hp1'] and current_price > 0 and current_price <= item['hp1']:
                    hp1_active = True
                    alert_triggered = True
                    # Sprawdź czy to nowy alert
                    if not item.get('hp1_triggered'):
                        triggered_levels.append(f"HP1: {item['hp1']:.2f}")
                        newly_triggered['hp1'] = True
                        logger.info(f"{item['ticker']}: Nowy alert HP1 osiągnięty przy {current_price:.2f} (HP1: {item['hp1']:.2f})")
                if hp1_active:
                    hp1_item.setBackground(QColor(255, 255, 150))  # Żółty
                table.setItem(row, 2, hp1_item)
                
                # HP2 - tylko jeśli HP1 już triggered (indeks kolumny zmieniony z 4 na 3)
                hp2_text = f"{item['hp2']:.2f}" if item['hp2'] else '-'
                hp2_item = QTableWidgetItem(hp2_text)
                hp2_item.setTextAlignment(Qt.AlignCenter)
                hp2_active = False
                if item['hp2'] and current_price > 0 and current_price <= item['hp2']:
                    # HP2 aktywny tylko jeśli HP1 był już wyzwolony
                    if item.get('hp1_triggered') or newly_triggered.get('hp1'):
                        hp2_active = True
                        alert_triggered = True
                        if not item.get('hp2_triggered'):
                            triggered_levels.append(f"HP2: {item['hp2']:.2f}")
                            newly_triggered['hp2'] = True
                            logger.info(f"{item['ticker']}: Nowy alert HP2 osiągnięty przy {current_price:.2f} (HP2: {item['hp2']:.2f})")
                if hp2_active:
                    hp2_item.setBackground(QColor(255, 255, 150))
                table.setItem(row, 3, hp2_item)
                
                # HP3 - tylko jeśli HP2 już triggered (indeks kolumny zmieniony z 5 na 4)
                hp3_text = f"{item['hp3']:.2f}" if item['hp3'] else '-'
                hp3_item = QTableWidgetItem(hp3_text)
                hp3_item.setTextAlignment(Qt.AlignCenter)
                hp3_active = False
                if item['hp3'] and current_price > 0 and current_price <= item['hp3']:
                    # HP3 aktywny tylko jeśli HP2 był już wyzwolony
                    if item.get('hp2_triggered') or newly_triggered.get('hp2'):
                        hp3_active = True
                        alert_triggered = True
                        if not item.get('hp3_triggered'):
                            triggered_levels.append(f"HP3: {item['hp3']:.2f}")
                            newly_triggered['hp3'] = True
                            logger.info(f"{item['ticker']}: Nowy alert HP3 osiągnięty przy {current_price:.2f} (HP3: {item['hp3']:.2f})")
                if hp3_active:
                    hp3_item.setBackground(QColor(255, 255, 150))
                table.setItem(row, 4, hp3_item)
                
                # HP4 - tylko jeśli HP3 już triggered (indeks kolumny zmieniony z 6 na 5)
                hp4_text = f"{item['hp4']:.2f}" if item['hp4'] else '-'
                hp4_item = QTableWidgetItem(hp4_text)
                hp4_item.setTextAlignment(Qt.AlignCenter)
                hp4_active = False
                if item['hp4'] and current_price > 0 and current_price <= item['hp4']:
                    # HP4 aktywny tylko jeśli HP3 był już wyzwolony
                    if item.get('hp3_triggered') or newly_triggered.get('hp3'):
                        hp4_active = True
                        alert_triggered = True
                        if not item.get('hp4_triggered'):
                            triggered_levels.append(f"HP4: {item['hp4']:.2f}")
                            newly_triggered['hp4'] = True
                            logger.info(f"{item['ticker']}: Nowy alert HP4 osiągnięty przy {current_price:.2f} (HP4: {item['hp4']:.2f})")
                if hp4_active:
                    hp4_item.setBackground(QColor(255, 255, 150))
                table.setItem(row, 5, hp4_item)
                
                # Zaktualizuj status w bazie danych jeśli są nowe alerty
                if newly_triggered:
                    self.db.update_watchlist_alert_status(
                        item['id'],
                        hp1=newly_triggered.get('hp1'),
                        hp2=newly_triggered.get('hp2'),
                        hp3=newly_triggered.get('hp3'),
                        hp4=newly_triggered.get('hp4')
                    )
                
                # Podświetl cały wiersz jeśli alert został wyzwolony
                if alert_triggered:
                    for col in range(6):
                        cell_item = table.item(row, col)
                        if cell_item:
                            cell_item.setBackground(QColor(255, 255, 150))
                
                # Dodaj do listy alertów tylko jeśli są NOWE wyzwolone poziomy
                if triggered_levels:
                    alerts.append({
                        'ticker': item['ticker'],
                        'current_price': current_price,
                        'levels': triggered_levels
                    })
                
                # Przyciski akcji
                action_widget = QWidget()
                action_layout = QHBoxLayout()
                action_layout.setContentsMargins(2, 2, 2, 2)
                
                # Przycisk edytuj
                edit_button = QPushButton('Edytuj')
                edit_button.setStyleSheet('background-color: #3b82f6; color: white; padding: 5px;')
                edit_button.clicked.connect(lambda checked, w=item: self.edit_watchlist(w))
                action_layout.addWidget(edit_button)
                
                if alert_triggered:
                    open_position_button = QPushButton('Otwórz pozycję')
                    open_position_button.setStyleSheet(
                        'background-color: #10b981; color: white; font-weight: bold; padding: 5px;'
                    )
                    open_position_button.clicked.connect(lambda checked, t=item['ticker']: self.open_position_from_watchlist(t))
                    action_layout.addWidget(open_position_button)
                
                delete_button = QPushButton('Usuń')
                delete_button.setStyleSheet('background-color: #ef4444; color: white; padding: 5px;')
                delete_button.clicked.connect(lambda checked, w=item: self.delete_from_watchlist(w))
                action_layout.addWidget(delete_button)
                
                action_widget.setLayout(action_layout)
                table.setCellWidget(row, 6, action_widget)
            
            # Wyświetl powiadomienia tylko o NOWYCH alertach
            if alerts:
                self.show_price_alerts(alerts)
        
        except Exception as e:
            logger.error(f"Błąd w load_watchlist: {type(e).__name__} - {str(e)}")
            logger.exception("Szczegóły błędu:")
            QMessageBox.critical(self, 'Błąd', 
                f'Wystąpił błąd podczas ładowania watchlisty:\n{str(e)}\n\n'
                f'Sprawdź logi w folderze Logs/')
    
    def load_watchlist_hybrid(self, force_refresh=False):
        """
        HYBRYDOWE ładowanie watchlist:
        1. INSTANT: Ładuj z cache (stare ceny jeśli są)
        2. Async refresh w tle jeśli cache stary
        """
        try:
            watchlist = self.db.get_watchlist(self.current_currency)
            
            if not watchlist:
                logger.info("Brak pozycji w watchlist")
                table = self.findChild(QTableWidget, f'watchlist_{self.current_currency}')
                if table:
                    table.setRowCount(0)
                return
            
            # Pobierz ceny z cache dla wszystkich tickerów watchlist
            tickers = [item['ticker'] for item in watchlist]
            
            # Sprawdź cache dla każdego tickera
            watchlist_with_cache = []
            needs_refresh = force_refresh
            
            for item in watchlist:
                ticker = item['ticker']
                cached_data = self.db.get_cached_price(ticker, max_age_minutes=999999)  # Pobierz nawet stary cache
                
                if cached_data:
                    item['cached_price'] = cached_data['last_price']  # Poprawione: last_price zamiast price
                    
                    # Oblicz wiek cache z last_update
                    try:
                        last_update = datetime.fromisoformat(cached_data['last_update'])
                        age_minutes = (datetime.now() - last_update).total_seconds() / 60
                        item['cache_age_minutes'] = age_minutes
                        
                        # Sprawdź czy cache jest stary
                        if age_minutes > 60:
                            needs_refresh = True
                    except Exception as e:
                        logger.warning(f"Błąd obliczania wieku cache dla {ticker}: {e}")
                        item['cache_age_minutes'] = 999
                        needs_refresh = True
                else:
                    item['cached_price'] = None
                    item['cache_age_minutes'] = None
                    needs_refresh = True
                
                watchlist_with_cache.append(item)
            
            # KROK 1: Wyświetl dane z cache (INSTANT!)
            self.display_watchlist_from_cache(watchlist_with_cache)
            
            # KROK 2: Async refresh w tle (jeśli potrzebny)
            if needs_refresh and self.auto_refresh_enabled:
                if not self.watchlist_refresh_in_progress:
                    logger.info(f"Watchlist cache wymaga odświeżenia - startujemy async refresh")
                    self.start_async_watchlist_refresh(watchlist_with_cache)
                else:
                    logger.debug("Refresh już w toku - pomijamy")
            else:
                logger.debug(f"Watchlist cache świeży - pomijamy refresh")
                
        except Exception as e:
            logger.error(f"Błąd w load_watchlist_hybrid: {e}", exc_info=True)
            QMessageBox.critical(self, 'Błąd', f'Nie udało się załadować watchlist:\n{str(e)}')
    
    def display_watchlist_from_cache(self, watchlist):
        """Wyświetla watchlist używając cen z cache - INSTANT!"""
        logger.debug(f"Wyświetlanie {len(watchlist)} pozycji watchlist z cache")
        
        table = self.findChild(QTableWidget, f'watchlist_{self.current_currency}')
        if not table:
            logger.warning(f"Tabela watchlist_{self.current_currency} nie znaleziona!")
            return
        
        table.setRowCount(0)
        
        # Lista alertów do wyświetlenia
        alerts = []
        
        for item in watchlist:
            row = table.rowCount()
            table.insertRow(row)
            
            # Ticker
            ticker_item = QTableWidgetItem(item['ticker'])
            ticker_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 0, ticker_item)
            
            # Użyj cached price jeśli dostępny, inaczej 0.0
            current_price = item.get('cached_price', 0.0) or 0.0
            
            # Cena aktualna
            current_price_item = QTableWidgetItem(f"{current_price:.2f}")
            current_price_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 1, current_price_item)
            
            # Sprawdź które poziomy zostały osiągnięte (SPADKI - cena <= HP)
            alert_triggered = False
            triggered_levels = []
            newly_triggered = {}
            
            # HP1
            hp1_text = f"{item['hp1']:.2f}" if item['hp1'] else '-'
            hp1_item = QTableWidgetItem(hp1_text)
            hp1_item.setTextAlignment(Qt.AlignCenter)
            hp1_active = False
            if item['hp1'] and current_price > 0 and current_price <= item['hp1']:
                hp1_active = True
                alert_triggered = True
                if not item.get('hp1_triggered'):
                    triggered_levels.append(f"HP1: {item['hp1']:.2f}")
                    newly_triggered['hp1'] = True
                    logger.info(f"{item['ticker']}: Nowy alert HP1 osiągnięty przy {current_price:.2f} (HP1: {item['hp1']:.2f})")
            if hp1_active:
                hp1_item.setBackground(QColor(255, 255, 150))
            table.setItem(row, 2, hp1_item)
            
            # HP2
            hp2_text = f"{item['hp2']:.2f}" if item['hp2'] else '-'
            hp2_item = QTableWidgetItem(hp2_text)
            hp2_item.setTextAlignment(Qt.AlignCenter)
            hp2_active = False
            if item['hp2'] and current_price > 0 and current_price <= item['hp2']:
                if item.get('hp1_triggered') or newly_triggered.get('hp1'):
                    hp2_active = True
                    alert_triggered = True
                    if not item.get('hp2_triggered'):
                        triggered_levels.append(f"HP2: {item['hp2']:.2f}")
                        newly_triggered['hp2'] = True
                        logger.info(f"{item['ticker']}: Nowy alert HP2 osiągnięty przy {current_price:.2f} (HP2: {item['hp2']:.2f})")
            if hp2_active:
                hp2_item.setBackground(QColor(255, 255, 150))
            table.setItem(row, 3, hp2_item)
            
            # HP3
            hp3_text = f"{item['hp3']:.2f}" if item['hp3'] else '-'
            hp3_item = QTableWidgetItem(hp3_text)
            hp3_item.setTextAlignment(Qt.AlignCenter)
            hp3_active = False
            if item['hp3'] and current_price > 0 and current_price <= item['hp3']:
                if item.get('hp2_triggered') or newly_triggered.get('hp2'):
                    hp3_active = True
                    alert_triggered = True
                    if not item.get('hp3_triggered'):
                        triggered_levels.append(f"HP3: {item['hp3']:.2f}")
                        newly_triggered['hp3'] = True
                        logger.info(f"{item['ticker']}: Nowy alert HP3 osiągnięty przy {current_price:.2f} (HP3: {item['hp3']:.2f})")
            if hp3_active:
                hp3_item.setBackground(QColor(255, 255, 150))
            table.setItem(row, 4, hp3_item)
            
            # HP4
            hp4_text = f"{item['hp4']:.2f}" if item['hp4'] else '-'
            hp4_item = QTableWidgetItem(hp4_text)
            hp4_item.setTextAlignment(Qt.AlignCenter)
            hp4_active = False
            if item['hp4'] and current_price > 0 and current_price <= item['hp4']:
                if item.get('hp3_triggered') or newly_triggered.get('hp3'):
                    hp4_active = True
                    alert_triggered = True
                    if not item.get('hp4_triggered'):
                        triggered_levels.append(f"HP4: {item['hp4']:.2f}")
                        newly_triggered['hp4'] = True
                        logger.info(f"{item['ticker']}: Nowy alert HP4 osiągnięty przy {current_price:.2f} (HP4: {item['hp4']:.2f})")
            if hp4_active:
                hp4_item.setBackground(QColor(255, 255, 150))
            table.setItem(row, 5, hp4_item)
            
            # Notatka
            note_text = item.get('note', '') or ''
            note_item = QTableWidgetItem(note_text)
            note_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 6, note_item)
            
            # Zaktualizuj status w bazie danych jeśli są nowe alerty
            if newly_triggered:
                self.db.update_watchlist_alert_status(
                    item['id'],
                    hp1=newly_triggered.get('hp1'),
                    hp2=newly_triggered.get('hp2'),
                    hp3=newly_triggered.get('hp3'),
                    hp4=newly_triggered.get('hp4')
                )
            
            # Podświetl cały wiersz jeśli alert został wyzwolony
            if alert_triggered:
                for col in range(7):  # 0-6: Ticker, Cena, HP1-HP4, Notatka
                    cell_item = table.item(row, col)
                    if cell_item:
                        cell_item.setBackground(QColor(255, 255, 150))
            
            # Dodaj do listy alertów tylko jeśli są NOWE wyzwolone poziomy
            if triggered_levels:
                alerts.append({
                    'ticker': item['ticker'],
                    'current_price': current_price,
                    'levels': triggered_levels
                })
            
            # Przyciski akcji
            action_widget = QWidget()
            action_layout = QHBoxLayout()
            action_layout.setContentsMargins(2, 2, 2, 2)
            
            # Przycisk edytuj
            edit_button = QPushButton('Edytuj')
            edit_button.setStyleSheet('background-color: #3b82f6; color: white; padding: 5px;')
            edit_button.clicked.connect(lambda checked, w=item: self.edit_watchlist(w))
            action_layout.addWidget(edit_button)
            
            if alert_triggered:
                open_position_button = QPushButton('Otwórz pozycję')
                open_position_button.setStyleSheet(
                    'background-color: #10b981; color: white; font-weight: bold; padding: 5px;'
                )
                open_position_button.clicked.connect(lambda checked, t=item['ticker']: self.open_position_from_watchlist(t))
                action_layout.addWidget(open_position_button)
            
            delete_button = QPushButton('Usuń')
            delete_button.setStyleSheet('background-color: #ef4444; color: white; padding: 5px;')
            delete_button.clicked.connect(lambda checked, w=item: self.delete_from_watchlist(w))
            action_layout.addWidget(delete_button)
            
            action_widget.setLayout(action_layout)
            table.setCellWidget(row, 7, action_widget)
        
        # Wyświetl powiadomienia tylko o NOWYCH alertach
        if alerts:
            self.show_price_alerts(alerts)
    
    def start_async_watchlist_refresh(self, watchlist):
        """Startuje asynchroniczne odświeżanie cen watchlist w tle"""
        if self.watchlist_refresh_in_progress:
            logger.debug("Refresh już w toku - pomijamy watchlist refresh")
            return
        
        self.watchlist_refresh_in_progress = True
        self.progress_label.setText("⏳ Odświeżanie watchlist...")
        
        # Uruchom w osobnym wątku
        refresh_thread = threading.Thread(
            target=self._refresh_watchlist_background,
            args=(watchlist,),
            daemon=True
        )
        refresh_thread.start()
    
    def _refresh_watchlist_background(self, watchlist):
        """Wykonywane w tle - pobiera świeże ceny dla watchlist i aktualizuje cache + UI"""
        try:
            logger.info("🔄 Watchlist background refresh rozpoczęty")
            start_time = datetime.now()
            
            # Przygotuj listę tickerów do odświeżenia
            tickers_to_refresh = []
            for item in watchlist:
                cache_age = item.get('cache_age_minutes')
                if cache_age is None or cache_age > 60:
                    tickers_to_refresh.append(item['ticker'])
            
            if not tickers_to_refresh:
                logger.info("Wszystkie ceny watchlist są świeże - koniec refresh")
                self.watchlist_refresh_in_progress = False
                return
            
            logger.info(f"Odświeżanie {len(tickers_to_refresh)} tickerów watchlist: {tickers_to_refresh}")
            
            # Pobierz świeże ceny (batch)
            fresh_prices = self.fetch_multiple_prices_batch(tickers_to_refresh)
            
            # Aktualizuj cache w bazie
            cache_updates = []
            for ticker in tickers_to_refresh:
                price = fresh_prices.get(ticker)
                if price and price > 0:
                    cache_updates.append({
                        'ticker': ticker,
                        'price': price,
                        'company_name': None,
                        'currency': self.current_currency
                    })
            
            if cache_updates:
                self.db.update_price_cache_batch(cache_updates)
                logger.info(f"✅ Zaktualizowano cache watchlist dla {len(cache_updates)} tickerów")
            
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"🔄 Watchlist background refresh zakończony w {elapsed:.2f}s")
            
            # Zaplanuj UI update w głównym wątku
            self.schedule_watchlist_ui_refresh()
            
        except Exception as e:
            logger.error(f"Błąd w watchlist background refresh: {e}", exc_info=True)
        finally:
            self.watchlist_refresh_in_progress = False
    
    def schedule_watchlist_ui_refresh(self):
        """Thread-safe: Odświeża watchlist UI w głównym wątku Qt"""
        QTimer.singleShot(0, self._watchlist_ui_refresh_after_background)
    
    def _watchlist_ui_refresh_after_background(self):
        """Odświeża watchlist UI po background refresh"""
        try:
            # Zamiast przeładowywać całą tabelę, zaktualizuj tylko ceny
            self.update_watchlist_prices_only()
            
            # Ustaw status tylko jeśli positions też się skończył
            if not self.positions_refresh_in_progress:
                self.progress_label.setText("✅ Watchlist zaktualizowana")
                # Resetuj status po 2 sekundach
                QTimer.singleShot(2000, self._set_ready_if_idle)
            
        except Exception as e:
            logger.error(f"Błąd w watchlist UI refresh: {e}", exc_info=True)
    
    def update_watchlist_prices_only(self):
        """Aktualizuje tylko ceny w watchlist bez przeładowywania całej tabeli (zachowuje scroll)"""
        try:
            table = self.findChild(QTableWidget, f'watchlist_{self.current_currency}')
            if not table:
                return
            
            watchlist = self.db.get_watchlist(self.current_currency)
            if not watchlist:
                return
            
            # Pobierz świeże ceny z cache
            for row, item in enumerate(watchlist):
                if row >= table.rowCount():
                    break
                
                ticker = item['ticker']
                cached_data = self.db.get_cached_price(ticker, max_age_minutes=999999)
                
                if cached_data:
                    current_price = cached_data['last_price']
                    
                    # Zaktualizuj tylko komórkę z ceną (kolumna 1)
                    price_item = table.item(row, 1)
                    if price_item:
                        price_item.setText(f"{current_price:.2f}")
                    
                    # Sprawdź alerty i zaktualizuj kolory
                    alert_triggered = False
                    
                    # HP1
                    if item['hp1'] and current_price > 0 and current_price <= item['hp1']:
                        alert_triggered = True
                    
                    # HP2
                    if item['hp2'] and current_price > 0 and current_price <= item['hp2']:
                        if item.get('hp1_triggered'):
                            alert_triggered = True
                    
                    # HP3
                    if item['hp3'] and current_price > 0 and current_price <= item['hp3']:
                        if item.get('hp2_triggered'):
                            alert_triggered = True
                    
                    # HP4
                    if item['hp4'] and current_price > 0 and current_price <= item['hp4']:
                        if item.get('hp3_triggered'):
                            alert_triggered = True
                    
                    # Podświetl wiersz jeśli alert
                    if alert_triggered:
                        for col in range(6):
                            cell_item = table.item(row, col)
                            if cell_item:
                                cell_item.setBackground(QColor(255, 255, 150))
                    else:
                        # Usuń podświetlenie jeśli nie ma alertu
                        for col in range(6):
                            cell_item = table.item(row, col)
                            if cell_item:
                                cell_item.setBackground(QColor(255, 255, 255))
            
            logger.debug(f"Zaktualizowano ceny dla {len(watchlist)} pozycji watchlist (scroll zachowany)")
            
        except Exception as e:
            logger.error(f"Błąd w update_watchlist_prices_only: {e}", exc_info=True)
    
    def show_price_alerts(self, alerts):
        """Wyświetla powiadomienia o osiągniętych poziomach cenowych"""
        if not alerts:
            return
        
        message = "🔔 ALERT CENOWY - SPADEK!\n\n"
        message += "Następujące spółki osiągnęły poziomy cenowe:\n\n"
        
        for alert in alerts:
            message += f"📊 {alert['ticker']}\n"
            message += f"   💰 Aktualna cena: {alert['current_price']:.2f}\n"
            message += f"   📉 Osiągnięte poziomy: {', '.join(alert['levels'])}\n\n"
        
        message += "✅ Kliknij 'Otwórz pozycję' aby dodać transakcję!"
        
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setWindowTitle('Alert Cenowy - Spadek')
        msg_box.setText(message)
        msg_box.setStyleSheet("QLabel{min-width: 400px;}")
        msg_box.exec_()
        
        logger.info(f"Wyświetlono powiadomienie o {len(alerts)} alertach cenowych (spadki)")
    
    def delete_from_watchlist(self, item):
        """Usuwa pozycję z watchlisty"""
        try:
            reply = QMessageBox.question(
                self, 'Usuń z obserwowanych', 
                f'Czy na pewno chcesz usunąć {item["ticker"]} z obserwowanych?',
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                self.db.delete_from_watchlist(item['id'])
                logger.warning(f"Usunięto {item[ticker]} z watchlisty")
                self.progress_label.setText(f'Usunięto {item["ticker"]} z obserwowanych')
                self.load_data()
        
        except Exception as e:
            logger.error(f"Błąd usuwania z watchlisty: {type(e).__name__} - {str(e)}")
            logger.exception("Szczegóły błędu:")
            QMessageBox.critical(self, 'Błąd', f'Błąd usuwania:\n{str(e)}')
    
    def open_position_from_watchlist(self, ticker):
        """Otwiera okno dodawania pozycji z wypełnionym tickerem"""
        logger.info(f"Otwieranie pozycji z watchlisty: {ticker}")
        
        # Wywołaj dialog dodawania pozycji z wpisanym tickerem
        self.add_position(self.current_currency, prefill_ticker=ticker)
    
    def sell_position(self, position, current_price):
        """Sprzedaje pozycję i przenosi do historii"""
        logger.info(f"Próba sprzedaży pozycji: {position['ticker']}")
        
        try:
            # Otwórz dialog do edycji ceny sprzedaży
            dialog = ClosePositionDialog(position, current_price, self.current_currency, self)
            if dialog.exec_() == QDialog.Accepted:
                close_data = dialog.close_data
                
                sell_price = close_data['sell_price']
                sell_date = close_data['sell_date']
                usd_rate = close_data['usd_rate']
                swap_cost = close_data.get('swap_cost', 0.0)  # Koszt SWAP z dialogu
                dividend_from_dialog = close_data.get('dividend', 0.0)  # Dywidenda z dialogu
                
                # Oblicz profit jako różnicę wartości: (ilość * cena_sprzedaży * kurs_sprzedaży) - (ilość * cena_zakupu * kurs_zakupu)
                instrument_type = position.get('instrument_type', 'Akcje')
                leverage = position.get('leverage', 1)
                direction = position.get('direction', 'Long')
                
                # Wartość sprzedaży w walucie instrumentu
                sell_value = sell_price * position['quantity']
                # Wartość zakupu w walucie instrumentu
                buy_value = position['buy_price'] * position['quantity']
                
                # Przelicz wartości na PLN jeśli pozycja ma zapisany kurs
                eur_rate_used = None
                usd_rate_used = None
                if self.current_currency == 'PLN':
                    if position.get('usd_rate'):
                        # Wartość sprzedaży - priorytet: kurs z dialogu, obecny kurs, kurs z pozycji
                        if usd_rate:
                            usd_rate_used = usd_rate
                        elif self.current_usd_rate:
                            usd_rate_used = self.current_usd_rate
                        else:
                            usd_rate_used = position.get('usd_rate')
                        
                        sell_value = sell_value * usd_rate_used
                        swap_cost = swap_cost * usd_rate_used
                        
                        # Wartość zakupu - zawsze przez kurs zakupu
                        buy_value = buy_value * position.get('usd_rate')
                    
                    elif position.get('eur_rate'):
                        # Wartość sprzedaży - priorytet: obecny kurs, kurs z pozycji
                        if self.current_eur_rate:
                            eur_rate_used = self.current_eur_rate
                        else:
                            eur_rate_used = position.get('eur_rate')
                        
                        sell_value = sell_value * eur_rate_used
                        swap_cost = swap_cost * eur_rate_used
                        
                        # Wartość zakupu - zawsze przez kurs zakupu
                        buy_value = buy_value * position.get('eur_rate')
                
                # Oblicz profit jako różnicę wartości
                if direction == 'Short':
                    # Dla short zarabiamy gdy cena spada
                    profit = buy_value - sell_value
                else:
                    # Dla long zarabiamy gdy cena rośnie
                    profit = sell_value - buy_value
                
                # Dodaj dywidendę do zysku (priorytet: wartość z dialogu, wartość z pozycji)
                dividend = dividend_from_dialog if dividend_from_dialog > 0 else (position.get('dividend', 0) or 0)
                profit += dividend
                
                # Odejmij koszt SWAP od zysku (SWAP już przeliczony przez kurs jeśli potrzeba)
                profit = profit - swap_cost
                
                logger.warning(f"Sprzedaż potwierdzona. Zysk przed SWAP: {profit + swap_cost:.2f}, SWAP: {swap_cost:.2f}, Zysk końcowy: {profit:.2f}")
                
                # Dodaj do historii
                history_id = self.db.add_to_history(
                    ticker=position['ticker'],
                    currency=position['currency'],  # Używaj waluty z pozycji, nie z bieżącej zakładki
                    buy_price=position['buy_price'],
                    sell_price=sell_price,
                    quantity=position['quantity'],
                    profit=profit,
                    buy_date=position['buy_date'],
                    sell_date=sell_date,
                    usd_rate=usd_rate_used or position.get('usd_rate'),
                    eur_rate=eur_rate_used or position.get('eur_rate'),
                    instrument_type=instrument_type,
                    leverage=leverage if instrument_type == 'CFD' else None,
                    direction=direction,
                    swap_daily=position.get('swap_daily'),
                    swap_cost=swap_cost,
                    dividend=dividend
                )
                
                logger.warning(f"Dodano do historii z ID: {history_id}")
                
                # Usuń z aktywnych pozycji
                self.db.delete_position(position['id'])
                
                logger.warning(f"Usunięto pozycję z aktywnych (ID: {position['id']})")
                
                self.progress_label.setText(f'Sprzedano {position["ticker"]} - Zysk: {profit:.2f}')
                self.load_data()
            else:
                logger.info("Sprzedaż anulowana przez użytkownika")
        
        except Exception as e:
            logger.error(f"Błąd w sell_position: {type(e).__name__} - {str(e)}")
            logger.exception("Szczegóły błędu:")
            QMessageBox.critical(self, 'Błąd', 
                f'Wystąpił błąd podczas zamykania pozycji:\n{str(e)}\n\n'
                f'Sprawdź logi w folderze Logs/')
            self.progress_label.setText('Błąd')
    
    def edit_position(self, position):
        """Edytuje istniejącą pozycję"""
        logger.info(f"Edycja pozycji: {position['ticker']}")
        
        try:
            dialog = EditPositionDialog(position, self.current_currency, self)
            if dialog.exec_() == QDialog.Accepted:
                data = dialog.position_data
                
                # Sprawdź czy użytkownik chce usunąć pozycję
                if data.get('delete'):
                    self.db.delete_position(position['id'])
                    logger.warning(f"Usunięto pozycję: {position['ticker']}")
                    self.progress_label.setText(f'Usunięto {position["ticker"]}')
                    self.load_data()
                    return
                
                # Aktualizuj w bazie danych
                self.db.update_position(
                    position_id=position['id'],
                    ticker=position['ticker'],  # ticker nie zmienia się
                    currency=position['currency'],  # Używaj waluty z pozycji, nie z bieżącej zakładki
                    buy_price=data['buy_price'],
                    quantity=data['quantity'],
                    purchase_date=data['buy_date'],
                    usd_rate=data['usd_rate'],
                    eur_rate=data.get('eur_rate'),
                    alert_price=data['alert_price'],
                    instrument_type=data.get('instrument_type', 'Akcje'),
                    leverage=data.get('leverage'),
                    direction=data.get('direction', 'Long'),
                    swap_daily=data.get('swap_daily'),
                    dividend=data.get('dividend')
                )
                
                logger.warning(f"Zaktualizowano pozycję: {position['ticker']}")
                self.progress_label.setText(f'Zaktualizowano {position["ticker"]}')
                self.load_data()
            else:
                logger.info("Edycja anulowana przez użytkownika")
        
        except Exception as e:
            logger.error(f"Błąd w edit_position: {type(e).__name__} - {str(e)}")
            logger.exception("Szczegóły błędu:")
            QMessageBox.critical(self, 'Błąd', 
                f'Wystąpił błąd podczas edycji pozycji:\n{str(e)}\n\n'
                f'Sprawdź logi w folderze Logs/')
            self.progress_label.setText('Błąd')
    
    def edit_history(self, history_item):
        """Edytuje transakcję w historii"""
        logger.info(f"Edycja historii: {history_item['ticker']}")
        
        try:
            dialog = EditHistoryDialog(history_item, self.current_currency, self)
            if dialog.exec_() == QDialog.Accepted:
                data = dialog.history_data
                
                # Sprawdź czy użytkownik chce usunąć transakcję
                if data.get('delete'):
                    self.db.delete_from_history(history_item['id'])
                    logger.warning(f"Usunięto transakcję z historii: {history_item['ticker']}")
                    self.progress_label.setText(f'Usunięto {history_item["ticker"]} z historii')
                    self.load_data()
                    return
                
                # Aktualizuj w bazie danych
                self.db.update_to_history(
                    history_id=history_item['id'],
                    ticker=history_item['ticker'],  # ticker nie zmienia się
                    currency=history_item['currency'],  # Używaj waluty z historii, nie z bieżącej zakładki
                    buy_price=data['buy_price'],
                    sell_price=data['sell_price'],
                    quantity=data['quantity'],
                    profit=data['profit'],
                    buy_date=data['buy_date'],
                    sell_date=data['sell_date'],
                    usd_rate=data['usd_rate'],
                    instrument_type=data.get('instrument_type', 'Akcje'),
                    leverage=data.get('leverage'),
                    direction=data.get('direction', 'Long'),
                    swap_daily=data.get('swap_daily'),
                    dividend=data.get('dividend', 0.0)
                )
                
                logger.warning(f"Zaktualizowano historię: {history_item['ticker']}")
                self.progress_label.setText(f'Zaktualizowano {history_item["ticker"]}')
                self.load_data()
            else:
                logger.info("Edycja anulowana przez użytkownika")
        
        except Exception as e:
            logger.error(f"Błąd w edit_history: {type(e).__name__} - {str(e)}")
            logger.exception("Szczegóły błędu:")
            QMessageBox.critical(self, 'Błąd', 
                f'Wystąpił błąd podczas edycji historii:\n{str(e)}\n\n'
                f'Sprawdź logi w folderze Logs/')
            self.progress_label.setText('Błąd')
    
    def edit_watchlist(self, watchlist_item):
        """Edytuje pozycję w watchliście"""
        logger.info(f"Edycja watchlisty: {watchlist_item['ticker']}")
        
        try:
            dialog = EditWatchlistDialog(watchlist_item, self.current_currency, self)
            if dialog.exec_() == QDialog.Accepted:
                data = dialog.watchlist_data
                
                # Sprawdź czy użytkownik chce usunąć pozycję
                if data.get('delete'):
                    self.db.delete_from_watchlist(watchlist_item['id'])
                    logger.warning(f"Usunięto z watchlisty: {watchlist_item['ticker']}")
                    self.progress_label.setText(f'Usunięto {watchlist_item["ticker"]} z obserwowanych')
                    self.load_data()
                    return
                
                # Aktualizuj w bazie danych
                self.db.update_watchlist(
                    watchlist_id=watchlist_item['id'],
                    ticker=watchlist_item['ticker'],  # ticker nie zmienia się
                    currency=watchlist_item['currency'],  # Używaj waluty z watchlisty, nie z bieżącej zakładki
                    hp1=data['hp1'],
                    hp2=data['hp2'],
                    hp3=data['hp3'],
                    hp4=data['hp4'],
                    note=data.get('note')
                )
                
                logger.warning(f"Zaktualizowano watchlistę: {watchlist_item['ticker']}")
                self.progress_label.setText(f'Zaktualizowano {watchlist_item["ticker"]}')
                self.load_data()
            else:
                logger.info("Edycja anulowana przez użytkownika")
        
        except Exception as e:
            logger.error(f"Błąd w edit_watchlist: {type(e).__name__} - {str(e)}")
            logger.exception("Szczegóły błędu:")
            QMessageBox.critical(self, 'Błąd', 
                f'Wystąpił błąd podczas edycji watchlisty:\n{str(e)}\n\n'
                f'Sprawdź logi w folderze Logs/')
            self.progress_label.setText('Błąd')
    
    def show_portfolio_module(self):
        """Przełącza na moduł portfolio"""
        self.module_stack.setCurrentIndex(0)
        
        # Zmień style przycisków
        self.portfolio_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                border-radius: 10px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        
        self.budget_btn.setStyleSheet("""
            QPushButton {
                background-color: #6b7280;
                color: white;
                border-radius: 10px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #4b5563;
            }
        """)
        
        logger.info("Przełączono na moduł Portfolio")
    
    def show_budget_module(self):
        """Przełącza na moduł budżetu domowego"""
        # Sprawdź czy moduł budżetu jest włączony
        if not hasattr(self, 'budget_widget') or self.budget_widget is None:
            QMessageBox.warning(
                self,
                'Moduł wyłączony',
                'Moduł Budżet Domowy jest wyłączony.\n\n'
                'Możesz go włączyć w menu Ustawienia (⚙️).'
            )
            return
        
        self.module_stack.setCurrentWidget(self.budget_widget)
        
        # Zmień style przycisków
        self.portfolio_btn.setStyleSheet("""
            QPushButton {
                background-color: #6b7280;
                color: white;
                border-radius: 10px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #4b5563;
            }
        """)
        
        self.budget_btn.setStyleSheet("""
            QPushButton {
                background-color: #f59e0b;
                color: white;
                border-radius: 10px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #d97706;
            }
        """)
        
        # Odśwież dane budżetu
        self.budget_widget.load_budget_data()
        
        logger.info("Przełączono na moduł Budżet Domowy")
    def show_media_module(self):
        """Przełącza na moduł MEDIA"""
        try:
            # Sprawdź czy moduł MEDIA jest włączony
            if not hasattr(self, 'media_widget') or self.media_widget is None:
                QMessageBox.warning(
                    self,
                    'Moduł wyłączony',
                    'Moduł MEDIA jest wyłączony.\n\n'
                    'Możesz go włączyć w menu Ustawienia (⚙️).'
                )
                return
            
            self.portfolio_btn.setStyleSheet("""
                QPushButton {
                    background-color: #6b7280;
                    color: white;
                    border-radius: 10px;
                    padding: 10px;
                }
                QPushButton:hover {
                    background-color: #4b5563;
                }
            """)
            
            if hasattr(self, 'budget_btn') and not self.budget_btn.isHidden():
                self.budget_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #6b7280;
                        color: white;
                        border-radius: 10px;
                        padding: 10px;
                    }
                    QPushButton:hover {
                        background-color: #4b5563;
                    }
                """)
            
            self.media_btn.setStyleSheet("""
                QPushButton {
                    background-color: #10b981;
                    color: white;
                    border-radius: 10px;
                    padding: 10px;
                }
                QPushButton:hover {
                    background-color: #059669;
                }
            """)
            
            self.module_stack.setCurrentWidget(self.media_widget)
            self.media_widget.update_dashboard()
            logger.info("Przełączono na moduł MEDIA")
            
        except Exception as e:
            logger.error(f"Błąd przełączania na moduł MEDIA: {e}")
        
    def show_settings_dialog(self):
        """Pokazuje dialog ustawień z eksportem/importem"""
        dialog = SettingsDialog(self.db, self)
        dialog.exec_()


# ============================================================
# DIALOG USTAWIEŃ
# ============================================================

class SettingsDialog(QDialog):
    """Dialog ustawień z funkcjami eksportu/importu całej bazy danych"""
    
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.parent_window = parent
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle('⚙️ Ustawienia')
        self.setMinimumSize(700, 600)
        self.setMaximumSize(900, 700)  # Maksymalny rozmiar
        
        # Główny layout
        main_layout = QVBoxLayout()
        
        # Tytuł (na górze, poza scrollem)
        title = QLabel('⚙️ USTAWIENIA I ZARZĄDZANIE DANYMI')
        title.setFont(QFont('Arial', 18, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #1f2937; margin: 20px;")
        main_layout.addWidget(title)
        
        # Scroll Area dla zawartości
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)
        
        # Widget zawierający całą zawartość
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        
        # ============================================================
        # SEKCJA WŁĄCZANIA/WYŁĄCZANIA MODUŁÓW
        # ============================================================
        modules_group = QWidget()
        modules_layout = QVBoxLayout()
        
        modules_title = QLabel('🔌 AKTYWNE MODUŁY')
        modules_title.setFont(QFont('Arial', 14, QFont.Bold))
        modules_title.setStyleSheet("color: #8b5cf6; margin-top: 10px;")
        modules_layout.addWidget(modules_title)
        
        # Opis
        modules_desc = QLabel('Włącz lub wyłącz moduły aplikacji. Wyłączone moduły nie będą widoczne w interfejsie.')
        modules_desc.setStyleSheet("color: #6b7280; margin-bottom: 10px;")
        modules_desc.setWordWrap(True)
        modules_layout.addWidget(modules_desc)
        
        # Checkbox Media
        self.media_checkbox = QCheckBox('📊 Moduł MEDIA (śledzenie zużycia: woda, prąd, gaz)')
        self.media_checkbox.setFont(QFont('Arial', 11))
        self.media_checkbox.setStyleSheet("margin: 5px 0;")
        self.media_checkbox.setChecked(self.db.is_module_enabled('media'))
        self.media_checkbox.stateChanged.connect(self.on_module_settings_changed)
        modules_layout.addWidget(self.media_checkbox)
        
        # Checkbox Budżet
        self.budget_checkbox = QCheckBox('💰 Moduł BUDŻET DOMOWY (przychody i wydatki)')
        self.budget_checkbox.setFont(QFont('Arial', 11))
        self.budget_checkbox.setStyleSheet("margin: 5px 0;")
        self.budget_checkbox.setChecked(self.db.is_module_enabled('budget'))
        self.budget_checkbox.stateChanged.connect(self.on_module_settings_changed)
        modules_layout.addWidget(self.budget_checkbox)
        
        # Info o konieczności restartu
        restart_info = QLabel('ℹ️ Po zmianie ustawień konieczne jest ponowne uruchomienie aplikacji')
        restart_info.setStyleSheet("color: #f59e0b; margin-top: 10px; font-style: italic;")
        restart_info.setWordWrap(True)
        modules_layout.addWidget(restart_info)
        
        modules_group.setLayout(modules_layout)
        layout.addWidget(modules_group)
        
        # Separator
        separator0 = QLabel()
        separator0.setStyleSheet("background-color: #e5e7eb; margin: 20px 0;")
        separator0.setMaximumHeight(2)
        layout.addWidget(separator0)
        
        # ============================================================
        # SEKCJA ZABEZPIECZENIA
        # ============================================================
        security_group = QWidget()
        security_layout = QVBoxLayout()
        
        security_title = QLabel('🔒 ZABEZPIECZENIA')
        security_title.setFont(QFont('Arial', 14, QFont.Bold))
        security_title.setStyleSheet("color: #dc2626; margin-top: 10px;")
        security_layout.addWidget(security_title)
        
        # Opis
        security_desc = QLabel('Zabezpiecz aplikację hasłem. Hasło będzie wymagane przy każdym uruchomieniu.')
        security_desc.setStyleSheet("color: #6b7280; margin-bottom: 10px;")
        security_desc.setWordWrap(True)
        security_layout.addWidget(security_desc)
        
        # Status autoryzacji
        if self.db.is_auth_enabled():
            status_text = "✅ Hasło jest włączone"
            status_color = "#10b981"
        else:
            status_text = "❌ Hasło nie jest ustawione"
            status_color = "#dc2626"
        
        self.auth_status_label = QLabel(status_text)
        self.auth_status_label.setStyleSheet(f"color: {status_color}; font-weight: bold; margin: 10px 0;")
        security_layout.addWidget(self.auth_status_label)
        
        # Przyciski zabezpieczeń
        security_buttons = QHBoxLayout()
        
        if not self.db.has_password_set():
            # Brak hasła - pokaż przycisk "Ustaw hasło"
            self.setup_password_btn = QPushButton('🔐 Ustaw hasło')
            self.setup_password_btn.setMinimumHeight(50)
            self.setup_password_btn.setFont(QFont('Arial', 11, QFont.Bold))
            self.setup_password_btn.setStyleSheet("""
                QPushButton {
                    background-color: #dc2626;
                    color: white;
                    border-radius: 8px;
                    padding: 10px;
                }
                QPushButton:hover {
                    background-color: #b91c1c;
                }
            """)
            self.setup_password_btn.clicked.connect(self.setup_password)
            security_buttons.addWidget(self.setup_password_btn)
        else:
            # Hasło ustawione - pokaż przyciski zarządzania
            self.change_password_btn = QPushButton('🔑 Zmień hasło')
            self.change_password_btn.setMinimumHeight(50)
            self.change_password_btn.setFont(QFont('Arial', 11, QFont.Bold))
            self.change_password_btn.setStyleSheet("""
                QPushButton {
                    background-color: #3b82f6;
                    color: white;
                    border-radius: 8px;
                    padding: 10px;
                }
                QPushButton:hover {
                    background-color: #2563eb;
                }
            """)
            self.change_password_btn.clicked.connect(self.change_password)
            security_buttons.addWidget(self.change_password_btn)
            
            self.disable_password_btn = QPushButton('🔓 Wyłącz hasło')
            self.disable_password_btn.setMinimumHeight(50)
            self.disable_password_btn.setFont(QFont('Arial', 11, QFont.Bold))
            self.disable_password_btn.setStyleSheet("""
                QPushButton {
                    background-color: #f59e0b;
                    color: white;
                    border-radius: 8px;
                    padding: 10px;
                }
                QPushButton:hover {
                    background-color: #d97706;
                }
            """)
            self.disable_password_btn.clicked.connect(self.disable_password)
            security_buttons.addWidget(self.disable_password_btn)
        
        security_layout.addLayout(security_buttons)
        
        # Opcje auto-lock (tylko jeśli hasło jest ustawione)
        if self.db.has_password_set():
            self.auto_lock_checkbox = QCheckBox('🔒 Automatyczna blokada po 30 minutach bezczynności')
            self.auto_lock_checkbox.setFont(QFont('Arial', 10))
            self.auto_lock_checkbox.setStyleSheet("margin: 10px 0;")
            self.auto_lock_checkbox.setChecked(
                self.db.get_setting('auto_lock_enabled', 'false').lower() == 'true'
            )
            self.auto_lock_checkbox.stateChanged.connect(self.toggle_auto_lock)
            security_layout.addWidget(self.auto_lock_checkbox)
            
            # Windows lock checkbox (tylko na Windows)
            if sys.platform == 'win32':
                self.windows_lock_checkbox = QCheckBox(
                    '🪟 Blokuj przy blokowaniu Windows (Win+L, Sleep, zmiana użytkownika)'
                )
                self.windows_lock_checkbox.setFont(QFont('Arial', 10))
                self.windows_lock_checkbox.setStyleSheet("margin: 5px 0;")
                self.windows_lock_checkbox.setChecked(
                    self.db.get_setting('lock_on_windows_lock', 'true').lower() == 'true'
                )
                self.windows_lock_checkbox.stateChanged.connect(self.toggle_windows_lock)
                security_layout.addWidget(self.windows_lock_checkbox)
        
        security_group.setLayout(security_layout)
        layout.addWidget(security_group)
        
        # Separator
        separator_security = QLabel()
        separator_security.setStyleSheet("background-color: #e5e7eb; margin: 20px 0;")
        separator_security.setMaximumHeight(2)
        layout.addWidget(separator_security)
        
        # ============================================================
        # SEKCJA PORTFOLIO
        # ============================================================
        portfolio_group = QWidget()
        portfolio_layout = QVBoxLayout()
        
        portfolio_title = QLabel('📊 PORTFOLIO')
        portfolio_title.setFont(QFont('Arial', 14, QFont.Bold))
        portfolio_title.setStyleSheet("color: #10b981; margin-top: 10px;")
        portfolio_layout.addWidget(portfolio_title)
        
        # Opis
        portfolio_desc = QLabel('Eksportuj lub importuj wszystkie dane portfolio (pozycje, historia, watchlista, strategie)')
        portfolio_desc.setStyleSheet("color: #6b7280; margin-bottom: 10px;")
        portfolio_desc.setWordWrap(True)
        portfolio_layout.addWidget(portfolio_desc)
        
        # Przyciski Portfolio
        portfolio_buttons = QHBoxLayout()
        
        self.export_portfolio_btn = QPushButton('📤 Eksportuj Portfolio')
        self.export_portfolio_btn.setMinimumHeight(50)
        self.export_portfolio_btn.setFont(QFont('Arial', 11, QFont.Bold))
        self.export_portfolio_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                border-radius: 8px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        self.export_portfolio_btn.clicked.connect(self.export_portfolio_full)
        portfolio_buttons.addWidget(self.export_portfolio_btn)
        
        self.import_portfolio_btn = QPushButton('📥 Importuj Portfolio')
        self.import_portfolio_btn.setMinimumHeight(50)
        self.import_portfolio_btn.setFont(QFont('Arial', 11, QFont.Bold))
        self.import_portfolio_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                border-radius: 8px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        self.import_portfolio_btn.clicked.connect(self.import_portfolio_full)
        portfolio_buttons.addWidget(self.import_portfolio_btn)
        
        portfolio_layout.addLayout(portfolio_buttons)
        portfolio_group.setLayout(portfolio_layout)
        layout.addWidget(portfolio_group)
        
        # Separator
        separator1 = QLabel()
        separator1.setStyleSheet("background-color: #e5e7eb; margin: 20px 0;")
        separator1.setMaximumHeight(2)
        layout.addWidget(separator1)
        
        # ============================================================
        # SEKCJA BUDŻET
        # ============================================================
        budget_group = QWidget()
        budget_layout = QVBoxLayout()
        
        budget_title = QLabel('💰 BUDŻET DOMOWY')
        budget_title.setFont(QFont('Arial', 14, QFont.Bold))
        budget_title.setStyleSheet("color: #f59e0b; margin-top: 10px;")
        budget_layout.addWidget(budget_title)
        
        # Opis
        budget_desc = QLabel('Eksportuj lub importuj wszystkie dane budżetu (przychody, wydatki)')
        budget_desc.setStyleSheet("color: #6b7280; margin-bottom: 10px;")
        budget_desc.setWordWrap(True)
        budget_layout.addWidget(budget_desc)
        
        # Przyciski Budżet
        budget_buttons = QHBoxLayout()
        
        self.export_budget_btn = QPushButton('📤 Eksportuj Budżet')
        self.export_budget_btn.setMinimumHeight(50)
        self.export_budget_btn.setFont(QFont('Arial', 11, QFont.Bold))
        self.export_budget_btn.setStyleSheet("""
            QPushButton {
                background-color: #f59e0b;
                color: white;
                border-radius: 8px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #d97706;
            }
        """)
        self.export_budget_btn.clicked.connect(self.export_budget_full)
        budget_buttons.addWidget(self.export_budget_btn)
        
        self.import_budget_btn = QPushButton('📥 Importuj Budżet')
        self.import_budget_btn.setMinimumHeight(50)
        self.import_budget_btn.setFont(QFont('Arial', 11, QFont.Bold))
        self.import_budget_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                border-radius: 8px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        self.import_budget_btn.clicked.connect(self.import_budget_full)
        budget_buttons.addWidget(self.import_budget_btn)
        
        budget_layout.addLayout(budget_buttons)
        budget_group.setLayout(budget_layout)
        layout.addWidget(budget_group)
        
        # Separator
        separator2 = QLabel()
        separator2.setStyleSheet("background-color: #e5e7eb; margin: 20px 0;")
        separator2.setMaximumHeight(2)
        layout.addWidget(separator2)
        
        # ============================================================
        # SEKCJA ZAAWANSOWANA
        # ============================================================
        advanced_group = QWidget()
        advanced_layout = QVBoxLayout()
        
        advanced_title = QLabel('🔧 ZAAWANSOWANE')
        advanced_title.setFont(QFont('Arial', 14, QFont.Bold))
        advanced_title.setStyleSheet("color: #6b7280; margin-top: 10px;")
        advanced_layout.addWidget(advanced_title)
        
        # Opis
        advanced_desc = QLabel('Optymalizacja bazy danych, statystyki')
        advanced_desc.setStyleSheet("color: #6b7280; margin-bottom: 10px;")
        advanced_desc.setWordWrap(True)
        advanced_layout.addWidget(advanced_desc)
        
        # Przyciski zaawansowane
        advanced_buttons = QHBoxLayout()
        
        self.optimize_db_btn = QPushButton('⚡ Optymalizuj Bazę')
        self.optimize_db_btn.setMinimumHeight(50)
        self.optimize_db_btn.setFont(QFont('Arial', 11, QFont.Bold))
        self.optimize_db_btn.setStyleSheet("""
            QPushButton {
                background-color: #8b5cf6;
                color: white;
                border-radius: 8px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #7c3aed;
            }
        """)
        self.optimize_db_btn.clicked.connect(self.optimize_database)
        advanced_buttons.addWidget(self.optimize_db_btn)
        
        self.db_stats_btn = QPushButton('📊 Statystyki Bazy')
        self.db_stats_btn.setMinimumHeight(50)
        self.db_stats_btn.setFont(QFont('Arial', 11, QFont.Bold))
        self.db_stats_btn.setStyleSheet("""
            QPushButton {
                background-color: #6b7280;
                color: white;
                border-radius: 8px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #4b5563;
            }
        """)
        self.db_stats_btn.clicked.connect(self.show_database_stats)
        advanced_buttons.addWidget(self.db_stats_btn)
        
        advanced_layout.addLayout(advanced_buttons)
        advanced_group.setLayout(advanced_layout)
        layout.addWidget(advanced_group)
        
        # Spacer na końcu zawartości
        layout.addStretch()
        
        # Ustaw content_widget w scroll area
        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)
        
        # Przycisk Zamknij (poza scrollem, na dole)
        close_btn = QPushButton('Zamknij')
        close_btn.setMinimumHeight(40)
        close_btn.setFont(QFont('Arial', 11))
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc2626;
                color: white;
                border-radius: 8px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #b91c1c;
            }
        """)
        close_btn.clicked.connect(self.close)
        main_layout.addWidget(close_btn)
        
        self.setLayout(main_layout)
    
    # ============================================================
    # ZARZĄDZANIE MODUŁAMI
    # ============================================================
    
    def on_module_settings_changed(self):
        """Obsługuje zmianę ustawień modułów"""
        try:
            # Zapisz ustawienia Media
            media_enabled = self.media_checkbox.isChecked()
            self.db.set_module_enabled('media', media_enabled)
            
            # Zapisz ustawienia Budżet
            budget_enabled = self.budget_checkbox.isChecked()
            self.db.set_module_enabled('budget', budget_enabled)
            
            logger.info(f"Ustawienia modułów zaktualizowane: Media={media_enabled}, Budżet={budget_enabled}")
            
            # Informacja o konieczności restartu
            QMessageBox.information(
                self,
                'Ustawienia zapisane',
                'Ustawienia zostały zapisane.\n\n'
                'Uruchom aplikację ponownie, aby zobaczyć zmiany.'
            )
            
        except Exception as e:
            logger.error(f"Błąd zapisywania ustawień modułów: {e}")
            QMessageBox.critical(self, 'Błąd', f'Błąd podczas zapisywania ustawień:\n{str(e)}')
    
    # ============================================================
    # ZARZĄDZANIE ZABEZPIECZENIAMI
    # ============================================================
    
    def setup_password(self):
        """Otwiera dialog konfiguracji hasła (pierwsze użycie)"""
        dialog = SetupPasswordDialog(self.db, self)
        if dialog.exec_() == QDialog.Accepted:
            # Odśwież status w ustawieniach
            QMessageBox.information(
                self,
                'Sukces',
                'Hasło zostało ustawione!\n\n'
                'Przy następnym uruchomieniu aplikacji będzie wymagane hasło.'
            )
            # Zamknij okno ustawień aby wymusić restart
            self.accept()
    
    def change_password(self):
        """Otwiera dialog zmiany hasła"""
        dialog = ChangePasswordDialog(self.db, self)
        dialog.exec_()
    
    def disable_password(self):
        """Wyłącza zabezpieczenie hasłem"""
        # Potwierdź obecne hasło przed wyłączeniem
        from PyQt5.QtWidgets import QInputDialog
        
        password, ok = QInputDialog.getText(
            self,
            'Potwierdzenie',
            'Wprowadź obecne hasło aby wyłączyć zabezpieczenie:',
            QLineEdit.Password
        )
        
        if not ok:
            return
        
        # Weryfikuj hasło
        success, message = self.db.verify_password(password)
        
        if not success:
            QMessageBox.critical(
                self,
                'Błąd',
                f'Nieprawidłowe hasło!\n{message}'
            )
            return
        
        # Potwierdź wyłączenie
        reply = QMessageBox.question(
            self,
            'Potwierdzenie',
            'Czy na pewno chcesz wyłączyć zabezpieczenie hasłem?\n\n'
            'Aplikacja nie będzie wymagać hasła przy uruchomieniu.',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                self.db.disable_auth()
                QMessageBox.information(
                    self,
                    'Sukces',
                    'Zabezpieczenie hasłem zostało wyłączone.\n\n'
                    'Aplikacja nie będzie już wymagać hasła.'
                )
                # Zamknij okno ustawień
                self.accept()
            except Exception as e:
                logger.error(f"Błąd wyłączania hasła: {e}")
                QMessageBox.critical(
                    self,
                    'Błąd',
                    f'Nie udało się wyłączyć hasła:\n{str(e)}'
                )
    
    def toggle_auto_lock(self, state):
        """Włącza/wyłącza automatyczną blokadę"""
        try:
            enabled = 'true' if state == Qt.Checked else 'false'
            self.db.set_setting('auto_lock_enabled', enabled)
            
            status = "włączona" if state == Qt.Checked else "wyłączona"
            logger.info(f"Auto-lock {status}")
            
        except Exception as e:
            logger.error(f"Błąd zmiany auto-lock: {e}")
    
    def toggle_windows_lock(self, state):
        """Włącza/wyłącza blokadę przy zdarzeniach Windows"""
        try:
            enabled = 'true' if state == Qt.Checked else 'false'
            self.db.set_setting('lock_on_windows_lock', enabled)
            
            status = "włączona" if state == Qt.Checked else "wyłączona"
            logger.info(f"Windows lock {status}")
            
            # Uruchom/zatrzymaj monitor jeśli potrzeba
            if hasattr(self.parent_window, 'session_monitor') and self.parent_window.session_monitor:
                if state == Qt.Checked and not self.parent_window.session_monitor.isRunning():
                    self.parent_window.session_monitor.start()
                    logger.info("Windows Session Monitor uruchomiony")
            
        except Exception as e:
            logger.error(f"Błąd zmiany lock_on_windows_lock: {e}")
    
    # ============================================================
    # EKSPORT/IMPORT PORTFOLIO
    # ============================================================
    
    def export_portfolio_full(self):
        """Eksportuje wszystkie dane portfolio do JSON"""
        try:
            import json
            from datetime import datetime
            
            # Dialog wyboru pliku
            default_name = f'portfolio_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                'Eksportuj Portfolio',
                default_name,
                'JSON Files (*.json)'
            )
            
            if not file_path:
                return
            
            logger.info(f"Eksportowanie portfolio do: {file_path}")
            
            # Zbierz wszystkie dane
            data = {
                'export_date': datetime.now().isoformat(),
                'version': '1.0',
                'portfolio': {
                    'positions_usd': self.db.get_positions('USD'),
                    'positions_pln': self.db.get_positions('PLN'),
                    'history_usd': self.db.get_history('USD'),
                    'history_pln': self.db.get_history('PLN'),
                    'watchlist_usd': self.db.get_watchlist('USD'),
                    'watchlist_pln': self.db.get_watchlist('PLN'),
                    'strategies_to_play': self.db.get_strategies_to_play(),
                    'strategies_playing': self.db.get_strategies_playing()
                }
            }
            
            # Zapisz do JSON
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            # Policz ile danych
            total_items = (
                len(data['portfolio']['positions_usd']) +
                len(data['portfolio']['positions_pln']) +
                len(data['portfolio']['history_usd']) +
                len(data['portfolio']['history_pln']) +
                len(data['portfolio']['watchlist_usd']) +
                len(data['portfolio']['watchlist_pln']) +
                len(data['portfolio']['strategies_to_play']) +
                len(data['portfolio']['strategies_playing'])
            )
            
            logger.info(f"✅ Wyeksportowano {total_items} rekordów portfolio")
            QMessageBox.information(
                self,
                'Eksport zakończony',
                f'✅ Pomyślnie wyeksportowano {total_items} rekordów do:\n{file_path}'
            )
            
        except Exception as e:
            logger.error(f"Błąd eksportu portfolio: {e}", exc_info=True)
            QMessageBox.critical(self, 'Błąd', f'Błąd podczas eksportu:\n{str(e)}')
    
    def import_portfolio_full(self):
        """Importuje wszystkie dane portfolio z JSON"""
        try:
            import json
            
            # Ostrzeżenie
            reply = QMessageBox.question(
                self,
                'Potwierdzenie importu',
                '⚠️ UWAGA!\n\n'
                'Import nadpisze istniejące dane portfolio.\n'
                'Zalecamy wcześniejsze wykonanie backupu.\n\n'
                'Czy na pewno chcesz kontynuować?',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.No:
                return
            
            # Dialog wyboru pliku
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                'Importuj Portfolio',
                '',
                'JSON Files (*.json)'
            )
            
            if not file_path:
                return
            
            logger.info(f"Importowanie portfolio z: {file_path}")
            
            # Wczytaj JSON
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if 'portfolio' not in data:
                raise ValueError("Nieprawidłowy format pliku backup")
            
            portfolio = data['portfolio']
            imported_count = 0
            
            # Import pozycji USD
            for pos in portfolio.get('positions_usd', []):
                self.db.add_position(
                    ticker=pos['ticker'],
                    quantity=pos['quantity'],
                    buy_price=pos.get('buy_price', pos.get('purchase_price')),
                    purchase_date=pos.get('purchase_date', pos.get('buy_date')),
                    instrument_type=pos.get('instrument_type', 'Akcje'),
                    leverage=pos.get('leverage', 1),
                    currency='USD',
                    usd_rate=pos.get('usd_rate'),
                    eur_rate=pos.get('eur_rate'),
                    alert_price=pos.get('alert_price'),
                    direction=pos.get('direction', 'Long'),
                    swap_daily=pos.get('swap_daily'),
                    dividend=pos.get('dividend', 0)
                )
                imported_count += 1
            
            # Import pozycji PLN
            for pos in portfolio.get('positions_pln', []):
                self.db.add_position(
                    ticker=pos['ticker'],
                    quantity=pos['quantity'],
                    buy_price=pos.get('buy_price', pos.get('purchase_price')),
                    purchase_date=pos.get('purchase_date', pos.get('buy_date')),
                    instrument_type=pos.get('instrument_type', 'Akcje'),
                    leverage=pos.get('leverage', 1),
                    currency='PLN',
                    usd_rate=pos.get('usd_rate'),
                    eur_rate=pos.get('eur_rate'),
                    alert_price=pos.get('alert_price'),
                    direction=pos.get('direction', 'Long'),
                    swap_daily=pos.get('swap_daily'),
                    dividend=pos.get('dividend', 0)
                )
                imported_count += 1
            
            # Import historii USD
            for h in portfolio.get('history_usd', []):
                self.db.add_to_history(
                    ticker=h['ticker'],
                    buy_price=h['buy_price'],
                    sell_price=h['sell_price'],
                    quantity=h['quantity'],
                    profit=h['profit'],
                    buy_date=h['buy_date'],
                    sell_date=h['sell_date'],
                    currency='USD',
                    usd_rate=h.get('usd_rate'),
                    instrument_type=h.get('instrument_type', 'Akcje'),
                    leverage=h.get('leverage', 1),
                    direction=h.get('direction', 'Long'),
                    swap_daily=h.get('swap_daily')
                )
                imported_count += 1
            
            # Import historii PLN
            for h in portfolio.get('history_pln', []):
                self.db.add_to_history(
                    ticker=h['ticker'],
                    buy_price=h['buy_price'],
                    sell_price=h['sell_price'],
                    quantity=h['quantity'],
                    profit=h['profit'],
                    buy_date=h['buy_date'],
                    sell_date=h['sell_date'],
                    currency='PLN',
                    usd_rate=h.get('usd_rate'),
                    instrument_type=h.get('instrument_type', 'Akcje'),
                    leverage=h.get('leverage', 1),
                    direction=h.get('direction', 'Long'),
                    swap_daily=h.get('swap_daily')
                )
                imported_count += 1
            
            # Import watchlisty USD
            for w in portfolio.get('watchlist_usd', []):
                self.db.add_to_watchlist(
                    ticker=w['ticker'],
                    currency='USD',
                    hp1=w.get('hp1'),
                    hp2=w.get('hp2'),
                    hp3=w.get('hp3'),
                    hp4=w.get('hp4')
                )
                imported_count += 1
            
            # Import watchlisty PLN
            for w in portfolio.get('watchlist_pln', []):
                self.db.add_to_watchlist(
                    ticker=w['ticker'],
                    currency='PLN',
                    hp1=w.get('hp1'),
                    hp2=w.get('hp2'),
                    hp3=w.get('hp3'),
                    hp4=w.get('hp4')
                )
                imported_count += 1
            
            # Import strategii
            for s in portfolio.get('strategies_to_play', []):
                import json as json_lib
                self.db.add_strategy_to_play(
                    ticker=s['ticker'],
                    strategy_percent=s['strategy_percent'],
                    direction=s['direction'],
                    levels=json_lib.loads(s['levels']) if isinstance(s['levels'], str) else s['levels']
                )
                imported_count += 1
            
            for s in portfolio.get('strategies_playing', []):
                self.db.add_strategy_playing(
                    ticker=s['ticker'],
                    strategy_percent=s['strategy_percent'],
                    buy_price=s['buy_price'],
                    quantity=s['quantity'],
                    close_price=s['close_price'],
                    direction=s.get('direction', 'Wzrosty')
                )
                imported_count += 1
            
            logger.info(f"✅ Zaimportowano {imported_count} rekordów portfolio")
            QMessageBox.information(
                self,
                'Import zakończony',
                f'✅ Pomyślnie zaimportowano {imported_count} rekordów!\n\n'
                f'Odśwież aplikację aby zobaczyć zmiany.'
            )
            
            # Odśwież dane w głównym oknie
            if self.parent_window:
                self.parent_window.load_data(force_refresh=True)
            
        except Exception as e:
            logger.error(f"Błąd importu portfolio: {e}", exc_info=True)
            QMessageBox.critical(self, 'Błąd', f'Błąd podczas importu:\n{str(e)}')
    
    # ============================================================
    # EKSPORT/IMPORT BUDŻET
    # ============================================================
    
    def export_budget_full(self):
        """Eksportuje wszystkie dane budżetu do JSON"""
        try:
            import json
            from datetime import datetime
            
            # Dialog wyboru pliku
            default_name = f'budget_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                'Eksportuj Budżet',
                default_name,
                'JSON Files (*.json)'
            )
            
            if not file_path:
                return
            
            logger.info(f"Eksportowanie budżetu do: {file_path}")
            
            # Zbierz wszystkie dane budżetu
            data = {
                'export_date': datetime.now().isoformat(),
                'version': '1.0',
                'budget': {
                    'income': self.db.get_all_budget_income(),
                    'expenses': self.db.get_all_budget_expenses()
                }
            }
            
            # Zapisz do JSON
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            total_items = len(data['budget']['income']) + len(data['budget']['expenses'])
            
            logger.info(f"✅ Wyeksportowano {total_items} rekordów budżetu")
            QMessageBox.information(
                self,
                'Eksport zakończony',
                f'✅ Pomyślnie wyeksportowano {total_items} rekordów do:\n{file_path}'
            )
            
        except Exception as e:
            logger.error(f"Błąd eksportu budżetu: {e}", exc_info=True)
            QMessageBox.critical(self, 'Błąd', f'Błąd podczas eksportu:\n{str(e)}')
    
    def import_budget_full(self):
        """Importuje wszystkie dane budżetu z JSON"""
        try:
            import json
            
            # Ostrzeżenie
            reply = QMessageBox.question(
                self,
                'Potwierdzenie importu',
                '⚠️ UWAGA!\n\n'
                'Import nadpisze istniejące dane budżetu.\n'
                'Zalecamy wcześniejsze wykonanie backupu.\n\n'
                'Czy na pewno chcesz kontynuować?',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.No:
                return
            
            # Dialog wyboru pliku
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                'Importuj Budżet',
                '',
                'JSON Files (*.json)'
            )
            
            if not file_path:
                return
            
            logger.info(f"Importowanie budżetu z: {file_path}")
            
            # Wczytaj JSON
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if 'budget' not in data:
                raise ValueError("Nieprawidłowy format pliku backup")
            
            budget = data['budget']
            imported_count = 0
            
            # Import przychodów
            for income in budget.get('income', []):
                self.db.add_budget_income(
                    year=income['year'],
                    month=income['month'],
                    day=income['day'],
                    category=income['category'],
                    amount=income['amount'],
                    comment=income.get('comment', '')
                )
                imported_count += 1
            
            # Import wydatków
            for expense in budget.get('expenses', []):
                self.db.add_budget_expense(
                    year=expense['year'],
                    month=expense['month'],
                    day=expense['day'],
                    category=expense['category'],
                    amount=expense['amount'],
                    comment=expense.get('comment', '')
                )
                imported_count += 1
            
            logger.info(f"✅ Zaimportowano {imported_count} rekordów budżetu")
            QMessageBox.information(
                self,
                'Import zakończony',
                f'✅ Pomyślnie zaimportowano {imported_count} rekordów!\n\n'
                f'Odśwież aplikację aby zobaczyć zmiany.'
            )
            
            # Odśwież dane w głównym oknie
            if self.parent_window and hasattr(self.parent_window, 'budget_widget'):
                self.parent_window.budget_widget.load_budget_data()
            
        except Exception as e:
            logger.error(f"Błąd importu budżetu: {e}", exc_info=True)
            QMessageBox.critical(self, 'Błąd', f'Błąd podczas importu:\n{str(e)}')
    
    # ============================================================
    # ZAAWANSOWANE
    # ============================================================
    
    def optimize_database(self):
        """Optymalizuje bazę danych"""
        try:
            reply = QMessageBox.question(
                self,
                'Optymalizacja bazy',
                'Optymalizacja może zająć kilka sekund.\n\n'
                'Kontynuować?',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            
            if reply == QMessageBox.No:
                return
            
            logger.info("Rozpoczęcie optymalizacji bazy danych...")
            
            # Pokaż progress
            progress = QMessageBox(self)
            progress.setWindowTitle('Optymalizacja')
            progress.setText('⚡ Optymalizacja bazy danych w toku...')
            progress.setStandardButtons(QMessageBox.NoButton)
            progress.show()
            QApplication.processEvents()
            
            # Wykonaj optymalizację
            success = self.db.optimize_database()
            
            progress.close()
            
            if success:
                QMessageBox.information(
                    self,
                    'Optymalizacja zakończona',
                    '✅ Baza danych została pomyślnie zoptymalizowana!\n\n'
                    'Aplikacja powinna działać szybciej.'
                )
            else:
                QMessageBox.warning(
                    self,
                    'Optymalizacja nie powiodła się',
                    '⚠️ Wystąpił błąd podczas optymalizacji.\n\n'
                    'Sprawdź logi dla szczegółów.'
                )
            
        except Exception as e:
            logger.error(f"Błąd optymalizacji: {e}", exc_info=True)
            QMessageBox.critical(self, 'Błąd', f'Błąd podczas optymalizacji:\n{str(e)}')
    
    def show_database_stats(self):
        """Pokazuje statystyki bazy danych"""
        try:
            stats = self.db.get_database_stats()
            
            stats_text = f"""
📊 STATYSTYKI BAZY DANYCH

📁 Rozmiar bazy: {stats['size_mb']:.2f} MB
📋 Liczba tabel: {stats['tables']}
🔍 Liczba indeksów: {stats['indexes']}

📈 DANE PORTFOLIO:
  • Pozycje: {stats['positions']}
  • Historia: {stats['history']}
  • Cache cen: {stats['cached_prices']}

💡 WSKAZÓWKI:
  • Jeśli baza >50MB, rozważ optymalizację
  • Cache cen odświeżany automatycznie co godzinę
  • Użyj "Optymalizuj Bazę" raz w miesiącu
            """
            
            QMessageBox.information(self, 'Statystyki Bazy Danych', stats_text)
            
        except Exception as e:
            logger.error(f"Błąd pobierania statystyk: {e}", exc_info=True)
            QMessageBox.critical(self, 'Błąd', f'Błąd podczas pobierania statystyk:\n{str(e)}')


def main():
    try:
        app = QApplication(sys.argv)
        app.setStyle('Fusion')  # Nowoczesny wygląd
        
        # Najpierw sprawdź czy potrzebne jest logowanie
        # Stwórz tymczasowe połączenie do bazy
        db_path = resource_path('portfolio.db')
        temp_db = Database(db_path)
        
        # Sprawdź czy autoryzacja jest włączona
        if temp_db.is_auth_enabled() and temp_db.has_password_set():
            # Pokaż TYLKO dialog logowania (bez aplikacji w tle)
            login_dialog = LoginDialog(temp_db)
            if login_dialog.exec_() != QDialog.Accepted:
                # Użytkownik zamknął dialog lub nie zalogował się
                sys.exit(0)
            # Po zalogowaniu - kontynuuj tworzenie aplikacji
            
        elif not temp_db.has_password_set() and temp_db.is_auth_enabled():
            # Pierwsze uruchomienie - ustaw hasło
            setup_dialog = SetupPasswordDialog(temp_db)
            if setup_dialog.exec_() != QDialog.Accepted:
                # Użytkownik anulował - uruchom bez hasła
                temp_db.set_auth_enabled(False)
        
        # TERAZ dopiero stwórz główne okno (po zalogowaniu lub bez hasła)
        window = MainWindow()
        
        # Załaduj dane
        window.initial_load()
        
        # Zainstaluj event filter dla śledzenia aktywności
        app.installEventFilter(window)
        
        # Pokaż główne okno (zmaksymalizowane)
        window.showMaximized()
        
        exit_code = app.exec_()
        sys.exit(exit_code)
        
    except Exception as e:
        logger.critical(f"Krytyczny błąd aplikacji: {type(e).__name__} - {str(e)}")
        logger.exception("Szczegóły błędu:")
        QMessageBox.critical(None, 'Błąd krytyczny', 
            f'Aplikacja napotkała błąd:\n{str(e)}\n\n'
            f'Sprawdź logi w folderze Logs/')
        sys.exit(1)


if __name__ == '__main__':
    main()