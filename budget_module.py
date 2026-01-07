# -*- coding: utf-8 -*-
"""
Moduł Budżetu Domowego
"""

import logging
import calendar
from datetime import datetime
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QTableWidget, QTableWidgetItem,
                             QHeaderView, QComboBox, QLineEdit, QDialog,
                             QFormLayout, QMessageBox, QScrollArea, QFrame,
                             QDoubleSpinBox, QTextEdit, QSpinBox)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QColor

logger = logging.getLogger(__name__)

# Definicje kategorii
INCOME_CATEGORIES = [
    "Wypłata",
    "Premia", 
    "800+",
    "Sprzedaż OLX",
    "Inne"
]

EXPENSE_CATEGORIES = {
    "Oszczędności": ["Mój skarb", "XTB Kids", "Wakacje", "Trading"],
    "Opłaty stałe": ["Czynsz", "Media", "Telefon", "Kredyt hipoteczny", 
                     "Kredyt konsumpcyjny", "Podatki", "Inne"],
    "Jedzenie": ["Dom", "Praca", "Miasto", "Inne"],
    "Transport": ["Paliwo", "Przeglądy i naprawy auta", "Ubezpieczenie auta", 
                  "Bilety", "Inne"],
    "Dzieci": ["Alimenty", "Ubrania", "Wizyty lekarskie", "Leki", 
               "Zajęcia dodatkowe", "Zabawki", "Inne"],
    "Okazje": ["Urodziny", "Święta Wielkanocne", "Święta Bożego Narodzenia", "Inne"],
    "Zakupy": ["Chemia", "Higiena osobista", "Wyposażenie mieszkania", 
               "Art. biurowe", "Ubrania"],
    "Remonty": ["Meble", "Dodatki", "Narzędzia", "Art. remontowe"],
    "Rozrywka": ["Multisport", "Lodowisko", "Kino/Teatr", "Koncerty", 
                 "Książki", "Turystyka", "Inne"]
}


class BudgetDialog(QDialog):
    """Dialog do dodawania/edycji pozycji budżetu"""
    
    def __init__(self, parent=None, entry_type='income', year=None, month=None, 
                 day=None, entry_data=None):
        super().__init__(parent)
        self.entry_type = entry_type  # 'income' lub 'expense'
        self.year = year
        self.month = month
        self.day = day
        self.entry_data = entry_data  # None dla nowego wpisu, dict dla edycji
        self.result_data = None
        
        self.init_ui()
        
        # Jeśli edycja, wypełnij dane
        if entry_data:
            self.fill_data(entry_data)
    
    def init_ui(self):
        """Inicjalizuje interfejs dialogu"""
        title = "Edytuj pozycję" if self.entry_data else "Dodaj pozycję"
        self.setWindowTitle(title)
        self.setMinimumWidth(400)
        
        layout = QFormLayout()
        
        # Data
        self.day_spin = QSpinBox()
        self.day_spin.setRange(1, 31)
        self.day_spin.setValue(self.day if self.day else 1)
        layout.addRow("Dzień:", self.day_spin)
        
        if self.entry_type == 'income':
            # Kategoria przychodu
            self.category_combo = QComboBox()
            self.category_combo.addItems(INCOME_CATEGORIES)
            layout.addRow("Kategoria:", self.category_combo)
        else:
            # Kategoria wydatku
            self.category_combo = QComboBox()
            self.category_combo.addItems(list(EXPENSE_CATEGORIES.keys()))
            self.category_combo.currentTextChanged.connect(self.on_category_changed)
            layout.addRow("Kategoria:", self.category_combo)
            
            # Podkategoria wydatku
            self.subcategory_combo = QComboBox()
            layout.addRow("Podkategoria:", self.subcategory_combo)
            
            # Wypełnij podkategorie dla pierwszej kategorii
            self.on_category_changed(self.category_combo.currentText())
        
        # Kwota
        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setRange(0, 1000000)
        self.amount_spin.setDecimals(2)
        self.amount_spin.setSuffix(" PLN")
        self.amount_spin.setValue(0.00)
        layout.addRow("Kwota:", self.amount_spin)
        
        # Komentarz
        self.comment_edit = QTextEdit()
        self.comment_edit.setMaximumHeight(80)
        self.comment_edit.setPlaceholderText("Opcjonalny komentarz...")
        layout.addRow("Komentarz:", self.comment_edit)
        
        # Przyciski
        button_layout = QHBoxLayout()
        
        save_btn = QPushButton("Zapisz")
        save_btn.clicked.connect(self.save)
        button_layout.addWidget(save_btn)
        
        cancel_btn = QPushButton("Anuluj")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addRow(button_layout)
        
        self.setLayout(layout)
    
    def on_category_changed(self, category):
        """Aktualizuje listę podkategorii"""
        self.subcategory_combo.clear()
        if category in EXPENSE_CATEGORIES:
            self.subcategory_combo.addItems(EXPENSE_CATEGORIES[category])
    
    def fill_data(self, data):
        """Wypełnia formularz danymi do edycji"""
        self.day_spin.setValue(data['day'])
        
        if self.entry_type == 'income':
            idx = self.category_combo.findText(data['category'])
            if idx >= 0:
                self.category_combo.setCurrentIndex(idx)
        else:
            idx = self.category_combo.findText(data['category'])
            if idx >= 0:
                self.category_combo.setCurrentIndex(idx)
            
            if 'subcategory' in data and data['subcategory']:
                idx = self.subcategory_combo.findText(data['subcategory'])
                if idx >= 0:
                    self.subcategory_combo.setCurrentIndex(idx)
        
        self.amount_spin.setValue(data['amount'])
        
        if 'comment' in data and data['comment']:
            self.comment_edit.setPlainText(data['comment'])
    
    def save(self):
        """Zapisuje dane i zamyka dialog"""
        self.result_data = {
            'year': self.year,
            'month': self.month,
            'day': self.day_spin.value(),
            'category': self.category_combo.currentText(),
            'amount': self.amount_spin.value(),
            'comment': self.comment_edit.toPlainText()
        }
        
        if self.entry_type == 'expense':
            self.result_data['subcategory'] = self.subcategory_combo.currentText()
        
        if self.entry_data:
            self.result_data['id'] = self.entry_data['id']
        
        self.accept()


class RecurringExpenseDialog(QDialog):
    """Dialog do dodawania/edycji wydatków cyklicznych"""
    
    def __init__(self, parent=None, recurring_data=None):
        super().__init__(parent)
        self.recurring_data = recurring_data  # None dla nowego, dict dla edycji
        self.result_data = None
        
        self.init_ui()
        
        if recurring_data:
            self.fill_data(recurring_data)
    
    def init_ui(self):
        """Inicjalizuje interfejs dialogu"""
        title = "Edytuj wydatek cykliczny" if self.recurring_data else "Dodaj wydatek cykliczny"
        self.setWindowTitle(title)
        self.setMinimumWidth(500)
        
        layout = QFormLayout()
        
        # Kategoria wydatku
        self.category_combo = QComboBox()
        self.category_combo.addItems(list(EXPENSE_CATEGORIES.keys()))
        self.category_combo.currentTextChanged.connect(self.on_category_changed)
        layout.addRow("Kategoria:", self.category_combo)
        
        # Podkategoria wydatku
        self.subcategory_combo = QComboBox()
        layout.addRow("Podkategoria:", self.subcategory_combo)
        
        # Wypełnij podkategorie dla pierwszej kategorii
        self.on_category_changed(self.category_combo.currentText())
        
        # Kwota
        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setRange(0, 1000000)
        self.amount_spin.setDecimals(2)
        self.amount_spin.setSuffix(" PLN")
        self.amount_spin.setValue(0.00)
        layout.addRow("Kwota:", self.amount_spin)
        
        # Dzień miesiąca
        self.day_spin = QSpinBox()
        self.day_spin.setRange(1, 31)
        self.day_spin.setValue(1)
        layout.addRow("Dzień miesiąca:", self.day_spin)
        
        # Data rozpoczęcia
        start_layout = QHBoxLayout()
        
        self.start_month_combo = QComboBox()
        months_pl = ["Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec",
                     "Lipiec", "Sierpień", "Wrzesień", "Październik", "Listopad", "Grudzień"]
        self.start_month_combo.addItems(months_pl)
        now = datetime.now()
        self.start_month_combo.setCurrentIndex(now.month - 1)
        start_layout.addWidget(self.start_month_combo)
        
        self.start_year_spin = QSpinBox()
        self.start_year_spin.setRange(2000, 2100)
        self.start_year_spin.setValue(now.year)
        start_layout.addWidget(self.start_year_spin)
        
        layout.addRow("Rozpoczęcie:", start_layout)
        
        # Typ czasu trwania
        self.duration_type_combo = QComboBox()
        self.duration_type_combo.addItems(["Bezterminowo", "Określona liczba miesięcy"])
        self.duration_type_combo.currentIndexChanged.connect(self.on_duration_type_changed)
        layout.addRow("Czas trwania:", self.duration_type_combo)
        
        # Liczba miesięcy (opcjonalnie)
        self.duration_months_spin = QSpinBox()
        self.duration_months_spin.setRange(1, 999)
        self.duration_months_spin.setValue(12)
        self.duration_months_spin.setEnabled(False)
        layout.addRow("Liczba miesięcy:", self.duration_months_spin)
        
        # Komentarz
        self.comment_edit = QTextEdit()
        self.comment_edit.setMaximumHeight(80)
        self.comment_edit.setPlaceholderText("Opcjonalny komentarz...")
        layout.addRow("Komentarz:", self.comment_edit)
        
        # Przyciski
        button_layout = QHBoxLayout()
        
        save_btn = QPushButton("Zapisz")
        save_btn.clicked.connect(self.save)
        button_layout.addWidget(save_btn)
        
        cancel_btn = QPushButton("Anuluj")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addRow(button_layout)
        
        self.setLayout(layout)
    
    def on_category_changed(self, category):
        """Aktualizuje listę podkategorii"""
        self.subcategory_combo.clear()
        if category in EXPENSE_CATEGORIES:
            self.subcategory_combo.addItems(EXPENSE_CATEGORIES[category])
    
    def on_duration_type_changed(self, index):
        """Aktywuje/dezaktywuje pole liczby miesięcy"""
        self.duration_months_spin.setEnabled(index == 1)  # 1 = "Określona liczba miesięcy"
    
    def fill_data(self, data):
        """Wypełnia formularz danymi do edycji"""
        idx = self.category_combo.findText(data['category'])
        if idx >= 0:
            self.category_combo.setCurrentIndex(idx)
        
        if 'subcategory' in data and data['subcategory']:
            idx = self.subcategory_combo.findText(data['subcategory'])
            if idx >= 0:
                self.subcategory_combo.setCurrentIndex(idx)
        
        self.amount_spin.setValue(data['amount'])
        self.day_spin.setValue(data['day_of_month'])
        
        self.start_month_combo.setCurrentIndex(data['start_month'] - 1)
        self.start_year_spin.setValue(data['start_year'])
        
        if data['duration_type'] == 'indefinite':
            self.duration_type_combo.setCurrentIndex(0)
        else:
            self.duration_type_combo.setCurrentIndex(1)
            if data['duration_months']:
                self.duration_months_spin.setValue(data['duration_months'])
        
        if 'comment' in data and data['comment']:
            self.comment_edit.setPlainText(data['comment'])
    
    def save(self):
        """Zapisuje dane i zamyka dialog"""
        duration_type = 'indefinite' if self.duration_type_combo.currentIndex() == 0 else 'months'
        duration_months = self.duration_months_spin.value() if duration_type == 'months' else None
        
        self.result_data = {
            'category': self.category_combo.currentText(),
            'subcategory': self.subcategory_combo.currentText(),
            'amount': self.amount_spin.value(),
            'day_of_month': self.day_spin.value(),
            'start_year': self.start_year_spin.value(),
            'start_month': self.start_month_combo.currentIndex() + 1,
            'duration_type': duration_type,
            'duration_months': duration_months,
            'comment': self.comment_edit.toPlainText()
        }
        
        if self.recurring_data:
            self.result_data['id'] = self.recurring_data['id']
        
        self.accept()


class BudgetWidget(QWidget):
    """Widget modułu budżetu domowego"""
    
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        
        # Aktualna data
        now = datetime.now()
        self.current_year = now.year
        self.current_month = now.month
        
        # Wybrany dzień w kalendarzu
        self.selected_day = None
        self.selected_cell = None  # Przechowuje zaznaczoną komórkę
        
        # Dane transakcji dziennych - inicjalizacja
        self.daily_data = {}
        self.daily_incomes = {}
        self.daily_expenses = {}
        
        self.init_ui()
        self.load_budget_data()
    
    def init_ui(self):
        """Inicjalizuje interfejs użytkownika"""
        layout = QVBoxLayout()
        
        # ============================================================
        # NAGŁÓWEK Z NAWIGACJĄ
        # ============================================================
        header_layout = QHBoxLayout()
        
        # Przycisk poprzedni miesiąc
        prev_btn = QPushButton("◄ Poprzedni")
        prev_btn.setFont(QFont('Arial', 12, QFont.Bold))
        prev_btn.clicked.connect(self.prev_month)
        header_layout.addWidget(prev_btn)
        
        # Wybór miesiąca i roku
        month_layout = QHBoxLayout()
        
        self.month_combo = QComboBox()
        self.month_combo.setFont(QFont('Arial', 12, QFont.Bold))
        months_pl = ["Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec",
                     "Lipiec", "Sierpień", "Wrzesień", "Październik", "Listopad", "Grudzień"]
        self.month_combo.addItems(months_pl)
        self.month_combo.setCurrentIndex(self.current_month - 1)
        self.month_combo.currentIndexChanged.connect(self.on_month_changed)
        month_layout.addWidget(self.month_combo)
        
        self.year_spin = QSpinBox()
        self.year_spin.setFont(QFont('Arial', 12, QFont.Bold))
        self.year_spin.setRange(2000, 2100)
        self.year_spin.setValue(self.current_year)
        self.year_spin.valueChanged.connect(self.on_year_changed)
        month_layout.addWidget(self.year_spin)
        
        header_layout.addLayout(month_layout)
        
        # Przycisk następny miesiąc
        next_btn = QPushButton("Następny ►")
        next_btn.setFont(QFont('Arial', 12, QFont.Bold))
        next_btn.clicked.connect(self.next_month)
        header_layout.addWidget(next_btn)
        
        # Przycisk dzisiaj
        today_btn = QPushButton("Dzisiaj")
        today_btn.setFont(QFont('Arial', 12, QFont.Bold))
        today_btn.clicked.connect(self.go_to_today)
        header_layout.addWidget(today_btn)
        
        layout.addLayout(header_layout)
        
        # ============================================================
        # GŁÓWNY UKŁAD: KATEGORIE (L) + KALENDARZ (R)
        # ============================================================
        content_layout = QHBoxLayout()
        
        # ============================================================
        # LEWA STRONA: KATEGORIE
        # ============================================================
        categories_widget = QWidget()
        categories_layout = QVBoxLayout()
        
        # Przychody
        income_label = QLabel("PRZYCHODY")
        income_label.setFont(QFont('Arial', 14, QFont.Bold))
        income_label.setStyleSheet("background-color: #90EE90; padding: 5px;")
        income_label.setAlignment(Qt.AlignCenter)
        categories_layout.addWidget(income_label)
        
        self.income_table = QTableWidget()
        self.income_table.setColumnCount(4)
        self.income_table.setHorizontalHeaderLabels(["Kategoria", "Kwota", "Komentarz", "Akcje"])
        self.income_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.income_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.income_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.income_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.income_table.setMaximumHeight(200)
        categories_layout.addWidget(self.income_table)
        
        add_income_btn = QPushButton("➕ Dodaj przychód")
        add_income_btn.setFont(QFont('Arial', 12, QFont.Bold))
        add_income_btn.clicked.connect(self.add_income)
        categories_layout.addWidget(add_income_btn)
        
        # Wydatki
        expense_label = QLabel("WYDATKI")
        expense_label.setFont(QFont('Arial', 14, QFont.Bold))
        expense_label.setStyleSheet("background-color: #FFB6C1; padding: 5px;")
        expense_label.setAlignment(Qt.AlignCenter)
        categories_layout.addWidget(expense_label)
        
        # Scroll area dla wydatków
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(400)
        
        expense_widget = QWidget()
        self.expense_layout = QVBoxLayout()
        expense_widget.setLayout(self.expense_layout)
        scroll.setWidget(expense_widget)
        
        categories_layout.addWidget(scroll)
        
        add_expense_btn = QPushButton("➕ Dodaj wydatek")
        add_expense_btn.setFont(QFont('Arial', 12, QFont.Bold))
        add_expense_btn.clicked.connect(self.add_expense)
        categories_layout.addWidget(add_expense_btn)
        
        # Przycisk do zarządzania wydatkami cyklicznymi
        recurring_btn = QPushButton("🔄 Wydatki stałe")
        recurring_btn.setFont(QFont('Arial', 12, QFont.Bold))
        recurring_btn.setStyleSheet("background-color: #E8F5E9;")
        recurring_btn.clicked.connect(self.manage_recurring_expenses)
        categories_layout.addWidget(recurring_btn)
        
        categories_widget.setLayout(categories_layout)
        content_layout.addWidget(categories_widget, 2)
        
        # ============================================================
        # PRAWA STRONA: KALENDARZ
        # ============================================================
        calendar_widget = QWidget()
        calendar_layout = QVBoxLayout()
        
        self.calendar_title = QLabel()
        self.calendar_title.setFont(QFont('Arial', 14, QFont.Bold))
        self.calendar_title.setAlignment(Qt.AlignCenter)
        self.update_calendar_title()
        calendar_layout.addWidget(self.calendar_title)
        
        self.calendar_table = QTableWidget()
        self.setup_calendar()
        self.calendar_table.itemClicked.connect(self.on_calendar_day_clicked)
        calendar_layout.addWidget(self.calendar_table)
        
        # ============================================================
        # OKNO Z TRANSAKCJAMI DLA WYBRANEGO DNIA
        # ============================================================
        day_transactions_label = QLabel("Transakcje w wybranym dniu")
        day_transactions_label.setFont(QFont('Arial', 12, QFont.Bold))
        day_transactions_label.setAlignment(Qt.AlignCenter)
        day_transactions_label.setStyleSheet("background-color: #E0E0E0; padding: 5px; margin-top: 10px;")
        calendar_layout.addWidget(day_transactions_label)
        
        self.day_transactions_table = QTableWidget()
        self.day_transactions_table.setColumnCount(4)
        self.day_transactions_table.setHorizontalHeaderLabels(["Typ", "Kategoria", "Kwota", "Komentarz"])
        self.day_transactions_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.day_transactions_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.day_transactions_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.day_transactions_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.day_transactions_table.setMaximumHeight(250)
        self.day_transactions_table.setMinimumHeight(150)
        calendar_layout.addWidget(self.day_transactions_table)
        
        calendar_widget.setLayout(calendar_layout)
        content_layout.addWidget(calendar_widget, 3)
        
        layout.addLayout(content_layout)
        
        # ============================================================
        # PODSUMOWANIE NA DOLE
        # ============================================================
        summary_frame = QFrame()
        summary_frame.setFrameShape(QFrame.StyledPanel)
        summary_layout = QHBoxLayout()
        
        # Dodaj stretch na początku
        summary_layout.addStretch()
        
        self.income_label = QLabel("Przychody: 0.00 PLN")
        self.income_label.setFont(QFont('Arial', 12, QFont.Bold))
        self.income_label.setStyleSheet("color: green;")
        summary_layout.addWidget(self.income_label)
        
        # Dodaj trochę przestrzeni między elementami
        summary_layout.addSpacing(100)
        
        self.expense_label = QLabel("Wydatki: 0.00 PLN")
        self.expense_label.setFont(QFont('Arial', 12, QFont.Bold))
        self.expense_label.setStyleSheet("color: red;")
        summary_layout.addWidget(self.expense_label)
        
        # Dodaj trochę przestrzeni między elementami
        summary_layout.addSpacing(100)
        
        self.balance_label = QLabel("Bilans: 0.00 PLN")
        self.balance_label.setFont(QFont('Arial', 12, QFont.Bold))
        summary_layout.addWidget(self.balance_label)
        
        # Dodaj stretch na końcu
        summary_layout.addStretch()
        
        summary_frame.setLayout(summary_layout)
        layout.addWidget(summary_frame)
        
        self.setLayout(layout)
    
    def setup_calendar(self):
        """Tworzy widok kalendarza dla aktualnego miesiąca"""
        # Pobierz liczbę dni w miesiącu
        num_days = calendar.monthrange(self.current_year, self.current_month)[1]
        first_weekday = calendar.monthrange(self.current_year, self.current_month)[0]
        
        # Ustal liczbę wierszy (tygodni)
        num_weeks = (num_days + first_weekday + 6) // 7
        
        self.calendar_table.clear()
        self.calendar_table.setRowCount(num_weeks)
        self.calendar_table.setColumnCount(8)  # 1 kolumna na numer tygodnia + 7 dni
        
        # Nagłówki - numer tygodnia w roku + dni tygodnia
        days_header = ["Tyg.", "Pon", "Wt", "Śr", "Czw", "Pt", "Sob", "Ndz"]
        self.calendar_table.setHorizontalHeaderLabels(days_header)
        
        # Zmniejsz rozmiar kafelków
        # Kolumna z numerem tygodnia - węższa
        self.calendar_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        
        # Dni tygodnia - równomiernie rozłożone
        for i in range(1, 8):
            self.calendar_table.horizontalHeader().setSectionResizeMode(i, QHeaderView.Stretch)
        
        # Zmniejsz wysokość wierszy
        for i in range(num_weeks):
            self.calendar_table.setRowHeight(i, 80)  # Zmniejszony z domyślnego
        
        # Wypełnij kalendarz
        day = 1
        for week in range(num_weeks):
            # Oblicz numer tygodnia w roku
            # Znajdź pierwszy dzień (poniedziałek lub inny) tego tygodnia w kalendarzu
            if week == 0 and first_weekday > 0:
                # Pierwszy wiersz - użyj pierwszego dnia miesiąca
                week_date = datetime(self.current_year, self.current_month, 1)
            elif day <= num_days:
                # Użyj pierwszego dnia tego tygodnia
                week_date = datetime(self.current_year, self.current_month, day)
            else:
                # Ostatni wiersz może nie mieć wszystkich dni
                week_date = datetime(self.current_year, self.current_month, num_days)
            
            # ZAWSZE używamy isocalendar()[1] dla numeru tygodnia w roku
            week_number = week_date.isocalendar()[1]
            
            # Komórka z numerem tygodnia - TYLKO numer tygodnia w roku
            week_item = QTableWidgetItem(str(week_number))
            week_item.setTextAlignment(Qt.AlignCenter)
            week_item.setBackground(QColor(220, 220, 220))
            week_item.setFont(QFont('Arial', 10, QFont.Bold))
            week_item.setFlags(Qt.ItemIsEnabled)  # Tylko do odczytu
            self.calendar_table.setItem(week, 0, week_item)
            
            for weekday in range(7):
                if week == 0 and weekday < first_weekday:
                    # Puste komórki przed pierwszym dniem miesiąca
                    item = QTableWidgetItem("")
                    item.setFlags(Qt.NoItemFlags)
                    self.calendar_table.setItem(week, weekday + 1, item)
                elif day <= num_days:
                    # Dzień miesiąca
                    day_text = str(day)
                    
                    # Sprawdź czy w tym dniu są wydatki i dodaj czerwoną kropkę
                    if day in self.daily_expenses and len(self.daily_expenses[day]) > 0:
                        day_text += "\n🔴"
                    
                    item = QTableWidgetItem(day_text)
                    item.setTextAlignment(Qt.AlignCenter | Qt.AlignTop)
                    
                    # Zwiększ czcionkę numeru dnia
                    font = QFont('Arial', 14, QFont.Bold)
                    item.setFont(font)
                    
                    # Podświetl dzisiejszą datę
                    now = datetime.now()
                    if (self.current_year == now.year and 
                        self.current_month == now.month and 
                        day == now.day):
                        item.setBackground(QColor(255, 255, 200))
                    # Weekendy - sobota (5) i niedziela (6)
                    elif weekday == 5:  # Sobota
                        item.setBackground(QColor(230, 240, 255))  # Jasnoniebieski
                    elif weekday == 6:  # Niedziela
                        item.setBackground(QColor(255, 240, 240))  # Jasnoczerwony
                    
                    self.calendar_table.setItem(week, weekday + 1, item)
                    day += 1
                else:
                    # Puste komórki po ostatnim dniu miesiąca
                    item = QTableWidgetItem("")
                    item.setFlags(Qt.NoItemFlags)
                    self.calendar_table.setItem(week, weekday + 1, item)
    
    def update_calendar_title(self):
        """Aktualizuje tytuł kalendarza z nazwą miesiąca i rokiem"""
        months_pl = ["STYCZEŃ", "LUTY", "MARZEC", "KWIECIEŃ", "MAJ", "CZERWIEC",
                     "LIPIEC", "SIERPIEŃ", "WRZESIEŃ", "PAŹDZIERNIK", "LISTOPAD", "GRUDZIEŃ"]
        
        month_name = months_pl[self.current_month - 1]
        title_text = f"{month_name} {self.current_year}"
        self.calendar_title.setText(title_text)
    
    def on_calendar_day_clicked(self, item):
        """Obsługuje kliknięcie na dzień w kalendarzu"""
        try:
            # Sprawdź czy to nie kolumna z tygodniem (kolumna 0)
            if item.column() == 0:
                return
            
            # Sprawdź czy komórka zawiera dzień (nie jest pusta)
            text = item.text().strip()
            if not text:
                return
            
            # Wyciągnij numer dnia (pierwsza linia tekstu)
            lines = text.split('\n')
            try:
                day = int(lines[0])
            except (ValueError, IndexError):
                return
            
            # Usuń zaznaczenie z poprzednio wybranej komórki
            if self.selected_cell:
                try:
                    # Sprawdź czy komórka nadal istnieje w tabeli
                    if self.selected_cell.tableWidget() == self.calendar_table:
                        # Przywróć normalną czcionkę (bez podkreślenia)
                        current_font = self.selected_cell.font()
                        new_font = QFont(current_font)
                        new_font.setUnderline(False)
                        self.selected_cell.setFont(new_font)
                except (RuntimeError, AttributeError) as e:
                    # Komórka już nie istnieje, ignoruj
                    logger.debug(f"Poprzednia zaznaczona komórka już nie istnieje: {e}")
                    pass
            
            # Zapisz wybrany dzień i komórkę
            self.selected_day = day
            self.selected_cell = item
            
            # Zaznacz wybraną komórkę (podkreślenie)
            current_font = item.font()
            new_font = QFont(current_font)
            new_font.setUnderline(True)
            item.setFont(new_font)
            
            # Zaktualizuj widok transakcji dla wybranego dnia
            self.update_day_transactions_view()
            
            logger.info(f"Wybrano dzień: {day}.{self.current_month}.{self.current_year}")
            
        except Exception as e:
            logger.error(f"Błąd w on_calendar_day_clicked: {e}", exc_info=True)
            QMessageBox.warning(self, "Błąd", f"Wystąpił błąd podczas wyboru dnia: {e}")
    
    def update_day_transactions_view(self):
        """Aktualizuje widok transakcji dla wybranego dnia"""
        try:
            self.day_transactions_table.setRowCount(0)
            
            if not self.selected_day:
                return
            
            # Sprawdź czy są jakieś transakcje dla tego dnia
            if not hasattr(self, 'daily_incomes') or not hasattr(self, 'daily_expenses'):
                logger.warning("Brak zainicjalizowanych danych daily_incomes lub daily_expenses")
                return
            
            day = self.selected_day
            row = 0
            
            # Dodaj przychody
            if day in self.daily_incomes:
                for income in self.daily_incomes[day]:
                    self.day_transactions_table.insertRow(row)
                    
                    # Typ
                    type_item = QTableWidgetItem("💰 Przychód")
                    type_item.setBackground(QColor(200, 255, 200))
                    type_item.setFont(QFont('Arial', 9, QFont.Bold))
                    self.day_transactions_table.setItem(row, 0, type_item)
                    
                    # Kategoria
                    category_item = QTableWidgetItem(income.get('category', 'Brak kategorii'))
                    self.day_transactions_table.setItem(row, 1, category_item)
                    
                    # Kwota
                    amount_item = QTableWidgetItem(f"{income.get('amount', 0):.2f} PLN")
                    amount_item.setFont(QFont('Arial', 9, QFont.Bold))
                    amount_item.setForeground(QColor(0, 128, 0))
                    self.day_transactions_table.setItem(row, 2, amount_item)
                    
                    # Komentarz
                    comment_item = QTableWidgetItem(income.get('comment', '') if income.get('comment') else "-")
                    self.day_transactions_table.setItem(row, 3, comment_item)
                    
                    row += 1
            
            # Dodaj wydatki
            if day in self.daily_expenses:
                for expense in self.daily_expenses[day]:
                    self.day_transactions_table.insertRow(row)
                    
                    # Typ
                    type_item = QTableWidgetItem("💸 Wydatek")
                    type_item.setBackground(QColor(255, 200, 200))
                    type_item.setFont(QFont('Arial', 9, QFont.Bold))
                    self.day_transactions_table.setItem(row, 0, type_item)
                    
                    # Kategoria (kategoria + podkategoria)
                    category_text = expense.get('category', 'Brak kategorii')
                    if expense.get('subcategory'):
                        category_text += f" / {expense['subcategory']}"
                    category_item = QTableWidgetItem(category_text)
                    self.day_transactions_table.setItem(row, 1, category_item)
                    
                    # Kwota
                    amount_item = QTableWidgetItem(f"{expense.get('amount', 0):.2f} PLN")
                    amount_item.setFont(QFont('Arial', 9, QFont.Bold))
                    amount_item.setForeground(QColor(255, 0, 0))
                    self.day_transactions_table.setItem(row, 2, amount_item)
                    
                    # Komentarz
                    comment_item = QTableWidgetItem(expense.get('comment', '') if expense.get('comment') else "-")
                    self.day_transactions_table.setItem(row, 3, comment_item)
                    
                    row += 1
            
            # Jeśli nie ma transakcji
            if row == 0:
                self.day_transactions_table.insertRow(0)
                no_data_item = QTableWidgetItem("Brak transakcji w tym dniu")
                no_data_item.setTextAlignment(Qt.AlignCenter)
                font = QFont('Arial', 10)
                font.setItalic(True)
                no_data_item.setFont(font)
                no_data_item.setForeground(QColor(128, 128, 128))
                self.day_transactions_table.setItem(0, 0, no_data_item)
                self.day_transactions_table.setSpan(0, 0, 1, 4)
                
        except Exception as e:
            logger.error(f"Błąd w update_day_transactions_view: {e}", exc_info=True)
            QMessageBox.warning(self, "Błąd", f"Wystąpił błąd podczas aktualizacji widoku transakcji: {e}")
    
    def load_budget_data(self):
        """Ładuje dane budżetu dla aktualnego miesiąca"""
        try:
            # Inicjalizuj puste struktury danych na wypadek błędu
            self.daily_data = {}
            self.daily_incomes = {}
            self.daily_expenses = {}
            
            # Generuj wydatki cykliczne dla bieżącego miesiąca
            try:
                self.db.generate_recurring_expenses_for_month(self.current_year, self.current_month)
            except Exception as e:
                logger.warning(f"Błąd generowania wydatków cyklicznych: {e}")
            
            # Pobierz dane z bazy
            incomes = self.db.get_budget_income(self.current_year, self.current_month)
            expenses = self.db.get_budget_expense(self.current_year, self.current_month)
            summary = self.db.get_budget_summary(self.current_year, self.current_month)
            
            # Aktualizuj podsumowanie
            self.income_label.setText(f"Przychody: {summary['total_income']:.2f} PLN")
            self.expense_label.setText(f"Wydatki: {summary['total_expense']:.2f} PLN")
            
            balance = summary['balance']
            color = "green" if balance >= 0 else "red"
            self.balance_label.setText(f"Bilans: {balance:.2f} PLN")
            self.balance_label.setStyleSheet(f"color: {color};")
            
            # Załaduj przychody
            self.load_income_data(incomes)
            
            # Załaduj wydatki
            self.load_expense_data(expenses)
            
            # Odśwież kalendarz
            self.update_calendar_with_data(incomes, expenses)
            
        except Exception as e:
            logger.error(f"Błąd ładowania danych budżetu: {e}", exc_info=True)
            QMessageBox.critical(self, "Błąd", f"Nie udało się załadować danych: {e}")
            
            # Upewnij się, że zmienne są zainicjalizowane nawet przy błędzie
            if not hasattr(self, 'daily_data'):
                self.daily_data = {}
            if not hasattr(self, 'daily_incomes'):
                self.daily_incomes = {}
            if not hasattr(self, 'daily_expenses'):
                self.daily_expenses = {}
    
    def load_income_data(self, incomes):
        """Ładuje dane przychodów do tabeli"""
        self.income_table.setRowCount(0)
        
        # Grupuj przychody po kategorii
        income_by_category = {}
        for income in incomes:
            cat = income['category']
            if cat not in income_by_category:
                income_by_category[cat] = []
            income_by_category[cat].append(income)
        
        row = 0
        for category in INCOME_CATEGORIES:
            if category in income_by_category:
                items = income_by_category[category]
                total = sum(item['amount'] for item in items)
                
                self.income_table.insertRow(row)
                
                # Kategoria
                cat_item = QTableWidgetItem(category)
                cat_item.setFont(QFont('Arial', 10, QFont.Bold))
                self.income_table.setItem(row, 0, cat_item)
                
                # Kwota
                amount_item = QTableWidgetItem(f"{total:.2f} PLN")
                self.income_table.setItem(row, 1, amount_item)
                
                # Komentarze (pokaż wszystkie)
                comments = []
                for item in items:
                    if item['comment']:
                        comments.append(f"[{item['day']}.{self.current_month}] {item['comment']}")
                comment_text = "\n".join(comments) if comments else "-"
                comment_item = QTableWidgetItem(comment_text)
                self.income_table.setItem(row, 2, comment_item)
                
                # Przyciski akcji
                actions_widget = QWidget()
                actions_layout = QHBoxLayout()
                actions_layout.setContentsMargins(2, 2, 2, 2)
                
                edit_btn = QPushButton("✏️")
                edit_btn.setMaximumWidth(30)
                edit_btn.clicked.connect(lambda checked, cat=category: self.edit_income(cat))
                actions_layout.addWidget(edit_btn)
                
                delete_btn = QPushButton("🗑️")
                delete_btn.setMaximumWidth(30)
                delete_btn.clicked.connect(lambda checked, cat=category: self.delete_income(cat))
                actions_layout.addWidget(delete_btn)
                
                actions_widget.setLayout(actions_layout)
                self.income_table.setCellWidget(row, 3, actions_widget)
                
                row += 1
    
    def load_expense_data(self, expenses):
        """Ładuje dane wydatków do layoutu kategorii"""
        # Wyczyść istniejące widgety
        while self.expense_layout.count():
            child = self.expense_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        # Grupuj wydatki po kategorii i podkategorii
        expense_by_category = {}
        for expense in expenses:
            cat = expense['category']
            subcat = expense.get('subcategory', '')
            
            if cat not in expense_by_category:
                expense_by_category[cat] = {}
            if subcat not in expense_by_category[cat]:
                expense_by_category[cat][subcat] = []
            
            expense_by_category[cat][subcat].append(expense)
        
        # Wyświetl kategorie
        for category in EXPENSE_CATEGORIES.keys():
            # Frame dla kategorii
            cat_frame = QFrame()
            cat_frame.setFrameShape(QFrame.StyledPanel)
            cat_layout = QVBoxLayout()
            
            # Nagłówek kategorii
            cat_total = 0
            if category in expense_by_category:
                for subcat_items in expense_by_category[category].values():
                    cat_total += sum(item['amount'] for item in subcat_items)
            
            cat_label = QLabel(f"{category} ({cat_total:.2f} PLN)")
            cat_label.setFont(QFont('Arial', 11, QFont.Bold))
            cat_label.setStyleSheet("background-color: #E0E0E0; padding: 3px;")
            cat_layout.addWidget(cat_label)
            
            # Podkategorie
            if category in expense_by_category:
                for subcategory in EXPENSE_CATEGORIES[category]:
                    if subcategory in expense_by_category[category]:
                        items = expense_by_category[category][subcategory]
                        total = sum(item['amount'] for item in items)
                        
                        subcat_layout = QHBoxLayout()
                        
                        subcat_label = QLabel(f"  • {subcategory}:")
                        subcat_layout.addWidget(subcat_label, 2)
                        
                        amount_label = QLabel(f"{total:.2f} PLN")
                        amount_label.setAlignment(Qt.AlignRight)
                        subcat_layout.addWidget(amount_label, 1)
                        
                        # Przyciski
                        edit_btn = QPushButton("✏️")
                        edit_btn.setMaximumWidth(30)
                        edit_btn.clicked.connect(
                            lambda checked, c=category, s=subcategory: 
                            self.edit_expense(c, s)
                        )
                        subcat_layout.addWidget(edit_btn)
                        
                        delete_btn = QPushButton("🗑️")
                        delete_btn.setMaximumWidth(30)
                        delete_btn.clicked.connect(
                            lambda checked, c=category, s=subcategory: 
                            self.delete_expense(c, s)
                        )
                        subcat_layout.addWidget(delete_btn)
                        
                        cat_layout.addLayout(subcat_layout)
            
            cat_frame.setLayout(cat_layout)
            self.expense_layout.addWidget(cat_frame)
        
        # Dodaj stretch na końcu
        self.expense_layout.addStretch()
    
    def update_calendar_with_data(self, incomes, expenses):
        """Aktualizuje kalendarz - przechowuje dane transakcji dla wybranego dnia"""
        # Grupuj dane po dniach - będzie używane do wyświetlenia szczegółów
        self.daily_data = {}
        self.daily_incomes = {}
        self.daily_expenses = {}
        
        for income in incomes:
            day = income['day']
            if day not in self.daily_data:
                self.daily_data[day] = {'income': 0, 'expense': 0}
                self.daily_incomes[day] = []
                self.daily_expenses[day] = []
            self.daily_data[day]['income'] += income['amount']
            self.daily_incomes[day].append(income)
        
        for expense in expenses:
            day = expense['day']
            if day not in self.daily_data:
                self.daily_data[day] = {'income': 0, 'expense': 0}
                self.daily_incomes[day] = []
                self.daily_expenses[day] = []
            self.daily_data[day]['expense'] += expense['amount']
            self.daily_expenses[day].append(expense)
        
        # Odśwież kalendarz wizualnie, aby pokazać kropki
        self.setup_calendar()
        
        # Odśwież widok transakcji dla zaznaczonego dnia (jeśli jakiś jest zaznaczony)
        if self.selected_day:
            self.update_day_transactions_view()
    
    def add_income(self):
        """Dodaje nowy przychód"""
        dialog = BudgetDialog(self, entry_type='income', 
                            year=self.current_year, 
                            month=self.current_month,
                            day=self.selected_day)  # Przekaż wybrany dzień
        
        if dialog.exec_() == QDialog.Accepted and dialog.result_data:
            data = dialog.result_data
            try:
                self.db.add_budget_income(
                    data['year'], data['month'], data['day'],
                    data['category'], data['amount'], data['comment']
                )
                self.load_budget_data()
                logger.info(f"Dodano przychód: {data['category']} - {data['amount']} PLN")
            except Exception as e:
                logger.error(f"Błąd dodawania przychodu: {e}")
                QMessageBox.critical(self, "Błąd", f"Nie udało się dodać przychodu: {e}")
    
    def edit_income(self, category):
        """Edytuje przychód dla danej kategorii"""
        # Pobierz wszystkie przychody dla tej kategorii
        incomes = self.db.get_budget_income(self.current_year, self.current_month)
        category_incomes = [i for i in incomes if i['category'] == category]
        
        if not category_incomes:
            return
        
        # Jeśli jest więcej niż jeden, pokaż listę do wyboru
        # Na razie edytujemy pierwszy
        income = category_incomes[0]
        
        dialog = BudgetDialog(self, entry_type='income',
                            year=self.current_year,
                            month=self.current_month,
                            entry_data=income)
        
        if dialog.exec_() == QDialog.Accepted and dialog.result_data:
            data = dialog.result_data
            try:
                self.db.update_budget_income(
                    data['id'], data['year'], data['month'], data['day'],
                    data['category'], data['amount'], data['comment']
                )
                self.load_budget_data()
                logger.info(f"Zaktualizowano przychód ID: {data['id']}")
            except Exception as e:
                logger.error(f"Błąd aktualizacji przychodu: {e}")
                QMessageBox.critical(self, "Błąd", f"Nie udało się zaktualizować przychodu: {e}")
    
    def delete_income(self, category):
        """Usuwa przychody dla danej kategorii"""
        reply = QMessageBox.question(
            self, "Potwierdzenie",
            f"Czy na pewno usunąć wszystkie przychody z kategorii '{category}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                incomes = self.db.get_budget_income(self.current_year, self.current_month)
                category_incomes = [i for i in incomes if i['category'] == category]
                
                for income in category_incomes:
                    self.db.delete_budget_income(income['id'])
                
                self.load_budget_data()
                logger.info(f"Usunięto przychody z kategorii: {category}")
            except Exception as e:
                logger.error(f"Błąd usuwania przychodów: {e}")
                QMessageBox.critical(self, "Błąd", f"Nie udało się usunąć przychodów: {e}")
    
    def add_expense(self):
        """Dodaje nowy wydatek"""
        dialog = BudgetDialog(self, entry_type='expense',
                            year=self.current_year,
                            month=self.current_month,
                            day=self.selected_day)  # Przekaż wybrany dzień
        
        if dialog.exec_() == QDialog.Accepted and dialog.result_data:
            data = dialog.result_data
            try:
                self.db.add_budget_expense(
                    data['year'], data['month'], data['day'],
                    data['category'], data['subcategory'],
                    data['amount'], data['comment']
                )
                self.load_budget_data()
                logger.info(f"Dodano wydatek: {data['category']}/{data['subcategory']} - {data['amount']} PLN")
            except Exception as e:
                logger.error(f"Błąd dodawania wydatku: {e}")
                QMessageBox.critical(self, "Błąd", f"Nie udało się dodać wydatku: {e}")
    
    def edit_expense(self, category, subcategory):
        """Edytuje wydatek dla danej kategorii/podkategorii"""
        expenses = self.db.get_budget_expense_by_category(
            self.current_year, self.current_month, category
        )
        subcat_expenses = [e for e in expenses if e.get('subcategory') == subcategory]
        
        if not subcat_expenses:
            return
        
        expense = subcat_expenses[0]
        
        dialog = BudgetDialog(self, entry_type='expense',
                            year=self.current_year,
                            month=self.current_month,
                            entry_data=expense)
        
        if dialog.exec_() == QDialog.Accepted and dialog.result_data:
            data = dialog.result_data
            try:
                self.db.update_budget_expense(
                    data['id'], data['year'], data['month'], data['day'],
                    data['category'], data['subcategory'],
                    data['amount'], data['comment']
                )
                self.load_budget_data()
                logger.info(f"Zaktualizowano wydatek ID: {data['id']}")
            except Exception as e:
                logger.error(f"Błąd aktualizacji wydatku: {e}")
                QMessageBox.critical(self, "Błąd", f"Nie udało się zaktualizować wydatku: {e}")
    
    def delete_expense(self, category, subcategory):
        """Usuwa wydatki dla danej kategorii/podkategorii"""
        reply = QMessageBox.question(
            self, "Potwierdzenie",
            f"Czy na pewno usunąć wszystkie wydatki z '{category}/{subcategory}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                expenses = self.db.get_budget_expense_by_category(
                    self.current_year, self.current_month, category
                )
                subcat_expenses = [e for e in expenses if e.get('subcategory') == subcategory]
                
                for expense in subcat_expenses:
                    self.db.delete_budget_expense(expense['id'])
                
                self.load_budget_data()
                logger.info(f"Usunięto wydatki: {category}/{subcategory}")
            except Exception as e:
                logger.error(f"Błąd usuwania wydatków: {e}")
                QMessageBox.critical(self, "Błąd", f"Nie udało się usunąć wydatków: {e}")
    
    def prev_month(self):
        """Przejdź do poprzedniego miesiąca"""
        if self.current_month == 1:
            self.current_month = 12
            self.current_year -= 1
        else:
            self.current_month -= 1
        
        # Resetuj wybrany dzień przy zmianie miesiąca
        self.selected_day = None
        self.selected_cell = None
        
        # Wyczyść tabelę transakcji dnia
        self.day_transactions_table.setRowCount(0)
        
        self.update_controls()
        self.update_calendar_title()
        self.load_budget_data()
    
    def next_month(self):
        """Przejdź do następnego miesiąca"""
        if self.current_month == 12:
            self.current_month = 1
            self.current_year += 1
        else:
            self.current_month += 1
        
        # Resetuj wybrany dzień przy zmianie miesiąca
        self.selected_day = None
        self.selected_cell = None
        
        # Wyczyść tabelę transakcji dnia
        self.day_transactions_table.setRowCount(0)
        
        self.update_controls()
        self.update_calendar_title()
        self.load_budget_data()
    
    def go_to_today(self):
        """Przejdź do aktualnego miesiąca"""
        now = datetime.now()
        self.current_year = now.year
        self.current_month = now.month
        
        # Resetuj wybrany dzień przy zmianie miesiąca
        self.selected_day = None
        self.selected_cell = None
        
        # Wyczyść tabelę transakcji dnia
        self.day_transactions_table.setRowCount(0)
        
        self.update_controls()
        self.update_calendar_title()
        self.load_budget_data()
    
    def on_month_changed(self, index):
        """Obsługa zmiany miesiąca w combobox"""
        self.current_month = index + 1
        
        # Resetuj wybrany dzień przy zmianie miesiąca
        self.selected_day = None
        self.selected_cell = None
        
        # Wyczyść tabelę transakcji dnia
        self.day_transactions_table.setRowCount(0)
        
        self.update_calendar_title()
        self.setup_calendar()
        self.load_budget_data()
    
    def on_year_changed(self, year):
        """Obsługa zmiany roku"""
        self.current_year = year
        
        # Resetuj wybrany dzień przy zmianie roku
        self.selected_day = None
        self.selected_cell = None
        
        # Wyczyść tabelę transakcji dnia
        self.day_transactions_table.setRowCount(0)
        
        self.update_calendar_title()
        self.setup_calendar()
        self.load_budget_data()
    
    def update_controls(self):
        """Aktualizuje kontrolki miesiąca i roku"""
        self.month_combo.blockSignals(True)
        self.year_spin.blockSignals(True)
        
        self.month_combo.setCurrentIndex(self.current_month - 1)
        self.year_spin.setValue(self.current_year)
        
        self.month_combo.blockSignals(False)
        self.year_spin.blockSignals(False)
        
        self.update_calendar_title()
        self.setup_calendar()
    
    def manage_recurring_expenses(self):
        """Otwiera okno zarządzania wydatkami cyklicznymi"""
        dialog = RecurringExpensesManagerDialog(self, self.db)
        if dialog.exec_() == QDialog.Accepted:
            # Odśwież dane po zmianach
            self.load_budget_data()


class RecurringExpensesManagerDialog(QDialog):
    """Dialog do zarządzania wydatkami cyklicznymi"""
    
    def __init__(self, parent=None, db=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Zarządzanie wydatkami stałymi")
        self.setMinimumSize(800, 500)
        
        self.init_ui()
        self.load_recurring_expenses()
    
    def init_ui(self):
        """Inicjalizuje interfejs"""
        layout = QVBoxLayout()
        
        # Nagłówek
        header = QLabel("Wydatki stałe (cykliczne)")
        header.setFont(QFont('Arial', 14, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)
        
        # Tabela
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "Kategoria", "Podkategoria", "Kwota", "Dzień", 
            "Początek", "Czas trwania", "Komentarz", "Akcje"
        ])
        
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        
        layout.addWidget(self.table)
        
        # Przyciski
        button_layout = QHBoxLayout()
        
        add_btn = QPushButton("➕ Dodaj wydatek stały")
        add_btn.setFont(QFont('Arial', 11, QFont.Bold))
        add_btn.clicked.connect(self.add_recurring_expense)
        button_layout.addWidget(add_btn)
        
        button_layout.addStretch()
        
        close_btn = QPushButton("Zamknij")
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def load_recurring_expenses(self):
        """Ładuje listę wydatków cyklicznych"""
        self.table.setRowCount(0)
        
        try:
            recurring = self.db.get_recurring_expenses()
            
            for rec in recurring:
                row = self.table.rowCount()
                self.table.insertRow(row)
                
                # Kategoria
                self.table.setItem(row, 0, QTableWidgetItem(rec['category']))
                
                # Podkategoria
                self.table.setItem(row, 1, QTableWidgetItem(rec.get('subcategory', '')))
                
                # Kwota
                amount_item = QTableWidgetItem(f"{rec['amount']:.2f} PLN")
                amount_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, 2, amount_item)
                
                # Dzień
                day_item = QTableWidgetItem(str(rec['day_of_month']))
                day_item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, 3, day_item)
                
                # Początek
                start = f"{rec['start_month']}/{rec['start_year']}"
                self.table.setItem(row, 4, QTableWidgetItem(start))
                
                # Czas trwania
                if rec['duration_type'] == 'indefinite':
                    duration = "Bezterminowo"
                else:
                    duration = f"{rec['duration_months']} miesięcy"
                self.table.setItem(row, 5, QTableWidgetItem(duration))
                
                # Komentarz
                self.table.setItem(row, 6, QTableWidgetItem(rec.get('comment', '')))
                
                # Przyciski akcji
                actions_widget = QWidget()
                actions_layout = QHBoxLayout()
                actions_layout.setContentsMargins(2, 2, 2, 2)
                
                edit_btn = QPushButton("✏️")
                edit_btn.setMaximumWidth(40)
                edit_btn.clicked.connect(lambda checked, r=rec: self.edit_recurring_expense(r))
                actions_layout.addWidget(edit_btn)
                
                delete_btn = QPushButton("🗑️")
                delete_btn.setMaximumWidth(40)
                delete_btn.clicked.connect(lambda checked, r=rec: self.delete_recurring_expense(r))
                actions_layout.addWidget(delete_btn)
                
                actions_widget.setLayout(actions_layout)
                self.table.setCellWidget(row, 7, actions_widget)
                
        except Exception as e:
            logger.error(f"Błąd ładowania wydatków cyklicznych: {e}")
            QMessageBox.critical(self, "Błąd", f"Nie udało się załadować wydatków: {e}")
    
    def add_recurring_expense(self):
        """Dodaje nowy wydatek cykliczny"""
        dialog = RecurringExpenseDialog(self)
        
        if dialog.exec_() == QDialog.Accepted and dialog.result_data:
            data = dialog.result_data
            try:
                self.db.add_recurring_expense(
                    data['category'], data['subcategory'], data['amount'],
                    data['day_of_month'], data['start_year'], data['start_month'],
                    data['duration_type'], data['duration_months'], data['comment']
                )
                self.load_recurring_expenses()
                logger.info(f"Dodano wydatek cykliczny: {data['category']}/{data['subcategory']}")
            except Exception as e:
                logger.error(f"Błąd dodawania wydatku cyklicznego: {e}")
                QMessageBox.critical(self, "Błąd", f"Nie udało się dodać wydatku: {e}")
    
    def edit_recurring_expense(self, recurring_data):
        """Edytuje wydatek cykliczny"""
        dialog = RecurringExpenseDialog(self, recurring_data)
        
        if dialog.exec_() == QDialog.Accepted and dialog.result_data:
            data = dialog.result_data
            try:
                self.db.update_recurring_expense(
                    data['id'], data['category'], data['subcategory'],
                    data['amount'], data['day_of_month'],
                    data['duration_type'], data['duration_months'], data['comment']
                )
                self.load_recurring_expenses()
                logger.info(f"Zaktualizowano wydatek cykliczny ID: {data['id']}")
            except Exception as e:
                logger.error(f"Błąd aktualizacji wydatku cyklicznego: {e}")
                QMessageBox.critical(self, "Błąd", f"Nie udało się zaktualizować wydatku: {e}")
    
    def delete_recurring_expense(self, recurring_data):
        """Usuwa wydatek cykliczny"""
        reply = QMessageBox.question(
            self, "Potwierdzenie",
            f"Czy na pewno usunąć wydatek cykliczny '{recurring_data['category']}/{recurring_data['subcategory']}'?\n\n"
            "Uwaga: Już wygenerowane wydatki nie zostaną usunięte.",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                self.db.delete_recurring_expense(recurring_data['id'])
                self.load_recurring_expenses()
                logger.info(f"Usunięto wydatek cykliczny ID: {recurring_data['id']}")
            except Exception as e:
                logger.error(f"Błąd usuwania wydatku cyklicznego: {e}")
                QMessageBox.critical(self, "Błąd", f"Nie udało się usunąć wydatku: {e}")