# -*- coding: utf-8 -*-
"""
Moduł MEDIA - śledzenie zużycia mediów (woda, prąd, gaz)
"""

import logging
import calendar
from datetime import datetime, timedelta
from collections import defaultdict
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QTableWidget, QTableWidgetItem,
                             QHeaderView, QComboBox, QLineEdit, QDialog,
                             QFormLayout, QMessageBox, QScrollArea, QFrame,
                             QDoubleSpinBox, QTextEdit, QSpinBox, QDateEdit,
                             QGroupBox, QGridLayout, QTabWidget)
from PyQt5.QtCore import Qt, pyqtSignal, QDate
from PyQt5.QtGui import QFont, QColor
import matplotlib
matplotlib.use('Qt5Agg')
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt

logger = logging.getLogger(__name__)

# Definicje typów mediów
UTILITY_TYPES = {
    "💧 Woda": {
        "unit": "m³",
        "icon": "💧",
        "color": "#3498db"
    },
    "⚡ Prąd": {
        "unit": "kWh",
        "icon": "⚡",
        "color": "#f39c12"
    },
    "🔥 Gaz": {
        "unit": "m³",
        "icon": "🔥",
        "color": "#e74c3c"
    }
}


class AddReadingDialog(QDialog):
    """Dialog do dodawania odczytu licznika"""
    
    def __init__(self, parent=None, db=None, utility_type=None, edit_data=None):
        super().__init__(parent)
        self.db = db
        self.utility_type = utility_type
        self.edit_data = edit_data
        self.result_data = None
        
        self.init_ui()
        
        if edit_data:
            self.fill_data(edit_data)
    
    def init_ui(self):
        """Inicjalizuje interfejs dialogu"""
        title = "Edytuj odczyt" if self.edit_data else "Dodaj odczyt licznika"
        self.setWindowTitle(title)
        self.setMinimumWidth(500)
        
        layout = QFormLayout()
        # Zwiększ czcionkę etykiet
        layout.setLabelAlignment(Qt.AlignRight)
        
        # Typ medium
        self.utility_combo = QComboBox()
        self.utility_combo.setFont(QFont('Arial', 12))
        self.utility_combo.addItems(list(UTILITY_TYPES.keys()))
        if self.utility_type:
            idx = self.utility_combo.findText(self.utility_type)
            if idx >= 0:
                self.utility_combo.setCurrentIndex(idx)
        self.utility_combo.currentTextChanged.connect(self.on_utility_changed)
        
        label1 = QLabel("Typ medium:")
        label1.setFont(QFont('Arial', 12, QFont.Bold))
        layout.addRow(label1, self.utility_combo)
        
        # Data odczytu
        self.date_edit = QDateEdit()
        self.date_edit.setFont(QFont('Arial', 12))
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setDisplayFormat("dd.MM.yyyy")
        
        label2 = QLabel("Data odczytu:")
        label2.setFont(QFont('Arial', 12, QFont.Bold))
        layout.addRow(label2, self.date_edit)
        
        # Stan licznika
        self.reading_spin = QDoubleSpinBox()
        self.reading_spin.setFont(QFont('Arial', 12))
        self.reading_spin.setRange(0, 999999.99)
        self.reading_spin.setDecimals(2)
        self.reading_spin.setValue(0.00)
        
        # Label dynamiczny dla jednostki
        self.unit_label = QLabel()
        self.unit_label.setFont(QFont('Arial', 12))
        reading_layout = QHBoxLayout()
        reading_layout.addWidget(self.reading_spin)
        reading_layout.addWidget(self.unit_label)
        
        label3 = QLabel("Stan licznika:")
        label3.setFont(QFont('Arial', 12, QFont.Bold))
        layout.addRow(label3, reading_layout)
        
        # Informacja o poprzednim odczycie
        self.prev_reading_label = QLabel()
        self.prev_reading_label.setFont(QFont('Arial', 11))
        self.prev_reading_label.setStyleSheet("color: #7f8c8d; font-style: italic;")
        layout.addRow("", self.prev_reading_label)
        
        # Komentarz
        self.comment_edit = QTextEdit()
        self.comment_edit.setFont(QFont('Arial', 11))
        self.comment_edit.setMaximumHeight(80)
        self.comment_edit.setPlaceholderText("Opcjonalny komentarz...")
        
        label4 = QLabel("Komentarz:")
        label4.setFont(QFont('Arial', 12, QFont.Bold))
        layout.addRow(label4, self.comment_edit)
        
        # Przyciski
        button_layout = QHBoxLayout()
        
        save_btn = QPushButton("💾 Zapisz")
        save_btn.setFont(QFont('Arial', 12, QFont.Bold))
        save_btn.clicked.connect(self.save)
        button_layout.addWidget(save_btn)
        
        cancel_btn = QPushButton("Anuluj")
        cancel_btn.setFont(QFont('Arial', 12))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addRow(button_layout)
        
        self.setLayout(layout)
        
        # Aktualizuj jednostkę
        self.on_utility_changed(self.utility_combo.currentText())
        
        # Pobierz ostatni odczyt
        self.update_previous_reading()
    
    def on_utility_changed(self, utility):
        """Aktualizuje jednostkę po zmianie typu medium"""
        if utility in UTILITY_TYPES:
            unit = UTILITY_TYPES[utility]["unit"]
            self.reading_spin.setSuffix(f" {unit}")
            self.unit_label.setText(unit)
            self.update_previous_reading()
    
    def update_previous_reading(self):
        """Aktualizuje informację o poprzednim odczycie"""
        utility = self.utility_combo.currentText()
        
        if not self.db:
            return
        
        try:
            last_reading = self.db.get_last_utility_reading(utility)
            
            if last_reading:
                date_str = last_reading['reading_date']
                value = last_reading['reading_value']
                unit = UTILITY_TYPES[utility]["unit"]
                
                self.prev_reading_label.setText(
                    f"Ostatni odczyt: {value:.2f} {unit} z dnia {date_str}"
                )
            else:
                self.prev_reading_label.setText("Brak poprzednich odczytów")
                
        except Exception as e:
            logger.error(f"Błąd pobierania ostatniego odczytu: {e}")
            self.prev_reading_label.setText("")
    
    def fill_data(self, data):
        """Wypełnia formularz danymi do edycji"""
        idx = self.utility_combo.findText(data['utility_type'])
        if idx >= 0:
            self.utility_combo.setCurrentIndex(idx)
        
        date = QDate.fromString(data['reading_date'], "yyyy-MM-dd")
        self.date_edit.setDate(date)
        
        self.reading_spin.setValue(data['reading_value'])
        
        if data.get('comment'):
            self.comment_edit.setPlainText(data['comment'])
    
    def save(self):
        """Zapisuje dane i zamyka dialog"""
        utility = self.utility_combo.currentText()
        reading_value = self.reading_spin.value()
        
        # Walidacja - sprawdź czy nowy odczyt nie jest mniejszy od poprzedniego
        if not self.edit_data:  # Tylko dla nowych odczytów
            last_reading = self.db.get_last_utility_reading(utility)
            if last_reading and reading_value < last_reading['reading_value']:
                reply = QMessageBox.question(
                    self,
                    "Ostrzeżenie",
                    f"⚠️ Nowy odczyt ({reading_value:.2f}) jest mniejszy od poprzedniego "
                    f"({last_reading['reading_value']:.2f}).\n\n"
                    "Czy na pewno chcesz kontynuować?",
                    QMessageBox.Yes | QMessageBox.No
                )
                
                if reply == QMessageBox.No:
                    return
        
        self.result_data = {
            'utility_type': utility,
            'reading_date': self.date_edit.date().toString("yyyy-MM-dd"),
            'reading_value': reading_value,
            'unit_cost': 0,  # Nie używamy kosztów
            'comment': self.comment_edit.toPlainText()
        }
        
        if self.edit_data:
            self.result_data['id'] = self.edit_data['id']
        
        self.accept()


class UtilityStatsWidget(QWidget):
    """Widget ze statystykami dla danego medium"""
    
    def __init__(self, parent=None, db=None, utility_type=None):
        super().__init__(parent)
        self.db = db
        self.utility_type = utility_type
        
        self.init_ui()
        self.update_stats()
    
    def init_ui(self):
        """Inicjalizuje interfejs"""
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        
        if self.utility_type in UTILITY_TYPES:
            icon = UTILITY_TYPES[self.utility_type]["icon"]
            color = UTILITY_TYPES[self.utility_type]["color"]
        else:
            icon = "📊"
            color = "#95a5a6"
        
        # Nagłówek
        header = QLabel(f"{icon} {self.utility_type}")
        header.setFont(QFont('Arial', 18, QFont.Bold))
        header.setStyleSheet(f"color: {color};")
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)
        
        # Statystyki
        self.stats_label = QLabel()
        self.stats_label.setFont(QFont('Arial', 15))
        self.stats_label.setWordWrap(True)
        self.stats_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.stats_label)
        
        self.setLayout(layout)
        
        # Styl ramki
        self.setStyleSheet(f"""
            QWidget {{
                background-color: white;
                border: 2px solid {color};
                border-radius: 8px;
            }}
        """)
    
    def update_stats(self):
        """Aktualizuje statystyki"""
        if not self.db:
            return
        
        try:
            stats = self.db.get_utility_stats(self.utility_type)
            
            if stats['count'] == 0:
                self.stats_label.setText("Brak danych")
                return
            
            unit = UTILITY_TYPES[self.utility_type]["unit"]
            
            text = f"""
<b>Liczba odczytów:</b> {stats['count']}<br>
<b>Ostatni odczyt:</b> {stats['last_reading']:.2f} {unit}<br>
<b>Zużycie w tym miesiącu:</b> {stats['current_month_usage']:.2f} {unit}<br>
<b>Średnie miesięczne:</b> {stats['avg_monthly']:.2f} {unit}<br>
<b>Trend:</b> {stats['trend_text']}
            """
            
            self.stats_label.setText(text)
            
        except Exception as e:
            logger.error(f"Błąd aktualizacji statystyk: {e}")
            self.stats_label.setText("Błąd ładowania danych")


class ConsumptionChartWidget(QWidget):
    """Widget z wykresem zużycia"""
    
    def __init__(self, parent=None, db=None):
        super().__init__(parent)
        self.db = db
        
        self.init_ui()
    
    def init_ui(self):
        """Inicjalizuje interfejs"""
        layout = QVBoxLayout()
        
        # Kontrolki
        controls = QHBoxLayout()
        
        label1 = QLabel("Typ medium:")
        label1.setFont(QFont('Arial', 12, QFont.Bold))
        controls.addWidget(label1)
        
        self.utility_combo = QComboBox()
        self.utility_combo.setFont(QFont('Arial', 12))
        self.utility_combo.addItems(list(UTILITY_TYPES.keys()))
        self.utility_combo.currentTextChanged.connect(self.update_chart)
        controls.addWidget(self.utility_combo)
        
        label2 = QLabel("Okres:")
        label2.setFont(QFont('Arial', 12, QFont.Bold))
        controls.addWidget(label2)
        
        self.period_combo = QComboBox()
        self.period_combo.setFont(QFont('Arial', 12))
        self.period_combo.addItems(["6 miesięcy", "12 miesięcy", "24 miesiące", "Wszystko"])
        self.period_combo.currentTextChanged.connect(self.update_chart)
        controls.addWidget(self.period_combo)
        
        controls.addStretch()
        
        refresh_btn = QPushButton("🔄 Odśwież")
        refresh_btn.setFont(QFont('Arial', 12, QFont.Bold))
        refresh_btn.clicked.connect(self.update_chart)
        controls.addWidget(refresh_btn)
        
        layout.addLayout(controls)
        
        # Wykres
        self.figure = Figure(figsize=(10, 5))
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)
        
        self.setLayout(layout)
        
        # Pierwsze załadowanie
        self.update_chart()
    
    def update_chart(self):
        """Aktualizuje wykres"""
        if not self.db:
            return
        
        utility = self.utility_combo.currentText()
        period = self.period_combo.currentText()
        
        # Określ liczbę miesięcy
        if period == "6 miesięcy":
            months = 6
        elif period == "12 miesięcy":
            months = 12
        elif period == "24 miesiące":
            months = 24
        else:
            months = None
        
        try:
            data = self.db.get_utility_consumption_data(utility, months)
            
            self.figure.clear()
            
            if not data:
                ax = self.figure.add_subplot(111)
                ax.text(0.5, 0.5, 'Brak danych do wyświetlenia', 
                       ha='center', va='center', fontsize=14)
                ax.set_xlim(0, 1)
                ax.set_ylim(0, 1)
                ax.axis('off')
                self.canvas.draw()
                return
            
            # Wykres słupkowy
            ax = self.figure.add_subplot(111)
            
            months_list = [item['month_label'] for item in data]
            consumption = [item['consumption'] for item in data]
            
            unit = UTILITY_TYPES[utility]["unit"]
            color = UTILITY_TYPES[utility]["color"]
            
            x = range(len(months_list))
            bars = ax.bar(x, consumption, color=color, alpha=0.7)
            
            ax.set_xlabel('Miesiąc', fontsize=10)
            ax.set_ylabel(f'Zużycie ({unit})', fontsize=10)
            ax.set_title(f'Zużycie - {utility}', fontsize=12, fontweight='bold')
            ax.set_xticks(x)
            ax.set_xticklabels(months_list, rotation=45, ha='right')
            ax.grid(True, alpha=0.3)
            
            # Dodaj wartości na słupkach
            for i, (bar, cons) in enumerate(zip(bars, consumption)):
                height = bar.get_height()
                if height > 0:
                    ax.text(bar.get_x() + bar.get_width()/2., height,
                           f'{cons:.1f}',
                           ha='center', va='bottom', fontsize=9)
            
            # Średnia
            if consumption:
                avg = sum(consumption) / len(consumption)
                ax.axhline(y=avg, color='red', linestyle='--', linewidth=2, 
                          label=f'Średnia: {avg:.1f} {unit}')
                ax.legend()
            
            self.figure.tight_layout()
            self.canvas.draw()
            
        except Exception as e:
            logger.error(f"Błąd aktualizacji wykresu: {e}", exc_info=True)


class ComparisonChartWidget(QWidget):
    """Widget z wykresem porównawczym"""
    
    def __init__(self, parent=None, db=None):
        super().__init__(parent)
        self.db = db
        
        self.init_ui()
    
    def init_ui(self):
        """Inicjalizuje interfejs"""
        layout = QVBoxLayout()
        
        # Kontrolki
        controls = QHBoxLayout()
        
        label_comp = QLabel("Porównaj:")
        label_comp.setFont(QFont('Arial', 12, QFont.Bold))
        controls.addWidget(label_comp)
        
        self.compare_combo = QComboBox()
        self.compare_combo.setFont(QFont('Arial', 12))
        self.compare_combo.addItems([
            "Bieżący vs poprzedni miesiąc",
            "Bieżący vs rok temu",
            "Wszystkie media - zużycie w obecnym miesiącu"
        ])
        self.compare_combo.currentTextChanged.connect(self.update_chart)
        controls.addWidget(self.compare_combo)
        
        controls.addStretch()
        
        refresh_btn = QPushButton("🔄 Odśwież")
        refresh_btn.setFont(QFont('Arial', 12, QFont.Bold))
        refresh_btn.clicked.connect(self.update_chart)
        controls.addWidget(refresh_btn)
        
        layout.addLayout(controls)
        
        # Wykres
        self.figure = Figure(figsize=(10, 5))
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)
        
        self.setLayout(layout)
        
        # Pierwsze załadowanie
        self.update_chart()
    
    def update_chart(self):
        """Aktualizuje wykres porównawczy"""
        if not self.db:
            return
        
        comparison_type = self.compare_combo.currentText()
        
        try:
            self.figure.clear()
            ax = self.figure.add_subplot(111)
            
            if comparison_type == "Wszystkie media - zużycie w obecnym miesiącu":
                # Porównanie zużycia wszystkich mediów w obecnym miesiącu
                data = []
                for utility in UTILITY_TYPES.keys():
                    consumption_data = self.db.get_utility_consumption_data(utility, 1)
                    if consumption_data:
                        data.append({
                            'utility': utility,
                            'consumption': consumption_data[0]['consumption']
                        })
                
                if not data:
                    ax.text(0.5, 0.5, 'Brak danych do wyświetlenia', 
                           ha='center', va='center', fontsize=14)
                    ax.set_xlim(0, 1)
                    ax.set_ylim(0, 1)
                    ax.axis('off')
                    self.canvas.draw()
                    return
                
                utilities = [item['utility'] for item in data]
                consumptions = [item['consumption'] for item in data]
                colors = [UTILITY_TYPES[u]["color"] for u in utilities]
                
                x = range(len(utilities))
                bars = ax.bar(x, consumptions, color=colors, alpha=0.7)
                
                ax.set_xlabel('Medium', fontsize=10)
                ax.set_ylabel('Zużycie', fontsize=10)
                ax.set_title('Zużycie mediów w bieżącym miesiącu', fontsize=12, fontweight='bold')
                ax.set_xticks(x)
                ax.set_xticklabels(utilities, rotation=0)
                ax.grid(True, alpha=0.3, axis='y')
                
                # Dodaj wartości
                for bar, cons, utility in zip(bars, consumptions, utilities):
                    height = bar.get_height()
                    unit = UTILITY_TYPES[utility]["unit"]
                    ax.text(bar.get_x() + bar.get_width()/2., height,
                           f'{cons:.1f} {unit}',
                           ha='center', va='bottom', fontsize=9, fontweight='bold')
                
            else:
                # Porównanie dla każdego medium osobno
                utilities = list(UTILITY_TYPES.keys())
                
                if comparison_type == "Bieżący vs poprzedni miesiąc":
                    months = 2
                    label1 = "Poprzedni"
                    label2 = "Bieżący"
                else:  # rok temu
                    months = 13
                    label1 = "Rok temu"
                    label2 = "Bieżący"
                
                data_by_utility = {}
                for utility in utilities:
                    consumption_data = self.db.get_utility_consumption_data(utility, months)
                    if len(consumption_data) >= 2:
                        if comparison_type == "Bieżący vs poprzedni miesiąc":
                            data_by_utility[utility] = {
                                'old': consumption_data[-2]['consumption'],
                                'new': consumption_data[-1]['consumption']
                            }
                        else:  # rok temu
                            data_by_utility[utility] = {
                                'old': consumption_data[0]['consumption'],
                                'new': consumption_data[-1]['consumption']
                            }
                
                if not data_by_utility:
                    ax.text(0.5, 0.5, 'Brak wystarczających danych do porównania', 
                           ha='center', va='center', fontsize=14)
                    ax.set_xlim(0, 1)
                    ax.set_ylim(0, 1)
                    ax.axis('off')
                    self.canvas.draw()
                    return
                
                utilities_to_plot = list(data_by_utility.keys())
                old_values = [data_by_utility[u]['old'] for u in utilities_to_plot]
                new_values = [data_by_utility[u]['new'] for u in utilities_to_plot]
                
                x = range(len(utilities_to_plot))
                width = 0.35
                
                ax.bar([i - width/2 for i in x], old_values, width, 
                      label=label1, alpha=0.7, color='gray')
                bars2 = ax.bar([i + width/2 for i in x], new_values, width, 
                              label=label2, alpha=0.7, 
                              color=[UTILITY_TYPES[u]["color"] for u in utilities_to_plot])
                
                ax.set_xlabel('Medium', fontsize=10)
                ax.set_ylabel('Zużycie', fontsize=10)
                ax.set_title(f'Porównanie zużycia: {comparison_type}', 
                            fontsize=12, fontweight='bold')
                ax.set_xticks(x)
                ax.set_xticklabels(utilities_to_plot, rotation=0)
                ax.legend()
                ax.grid(True, alpha=0.3, axis='y')
            
            self.figure.tight_layout()
            self.canvas.draw()
            
        except Exception as e:
            logger.error(f"Błąd aktualizacji wykresu porównawczego: {e}", exc_info=True)


class MediaWidget(QWidget):
    """Główny widget modułu MEDIA"""
    
    def __init__(self, parent=None, db=None):
        super().__init__(parent)
        self.db = db
        
        self.init_ui()
    
    def init_ui(self):
        """Inicjalizuje interfejs"""
        main_layout = QVBoxLayout()
        
        # Nagłówek
        header_layout = QHBoxLayout()
        
        title = QLabel("📊 MODUŁ MEDIA - Monitoring Zużycia")
        title.setFont(QFont('Arial', 22, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        add_btn = QPushButton("➕ Dodaj odczyt")
        add_btn.setFont(QFont('Arial', 13, QFont.Bold))
        add_btn.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                padding: 8px 16px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #229954;
            }
        """)
        add_btn.clicked.connect(self.add_reading)
        header_layout.addWidget(add_btn)
        
        main_layout.addLayout(header_layout)
        
        # Zakładki
        tabs = QTabWidget()
        tabs.setFont(QFont('Arial', 14, QFont.Bold))
        
        # Zakładka 1: Dashboard
        dashboard_tab = self.create_dashboard_tab()
        tabs.addTab(dashboard_tab, "📈 Dashboard")
        
        # Zakładka 2: Historia odczytów
        history_tab = self.create_history_tab()
        tabs.addTab(history_tab, "📋 Historia")
        
        # Zakładka 3: Wykresy
        charts_tab = self.create_charts_tab()
        tabs.addTab(charts_tab, "📊 Wykresy")
        
        # Zakładka 4: Analiza i porównania
        analysis_tab = self.create_analysis_tab()
        tabs.addTab(analysis_tab, "🔍 Analiza")
        
        main_layout.addWidget(tabs)
        
        self.setLayout(main_layout)
    
    def create_dashboard_tab(self):
        """Tworzy zakładkę Dashboard"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Statystyki dla każdego medium
        stats_layout = QHBoxLayout()
        
        self.stats_widgets = {}
        for utility in UTILITY_TYPES.keys():
            stats_widget = UtilityStatsWidget(self, self.db, utility)
            self.stats_widgets[utility] = stats_widget
            stats_layout.addWidget(stats_widget)
        
        layout.addLayout(stats_layout)
        
        # Szybki podgląd
        quick_view = QGroupBox("Szybki podgląd - ostatnie 3 miesiące")
        quick_view.setFont(QFont('Arial', 14, QFont.Bold))
        quick_layout = QVBoxLayout()
        
        self.quick_table = QTableWidget()
        self.quick_table.setColumnCount(4)
        self.quick_table.setHorizontalHeaderLabels([
            "Miesiąc", "💧 Woda", "⚡ Prąd", "🔥 Gaz"
        ])
        
        # Zwiększ czcionkę w tabeli
        self.quick_table.setFont(QFont('Arial', 14))
        header_quick = self.quick_table.horizontalHeader()
        header_quick.setFont(QFont('Arial', 15, QFont.Bold))
        header_quick.setSectionResizeMode(QHeaderView.Stretch)
        self.quick_table.setMaximumHeight(180)
        
        # Wyśrodkuj zawartość komórek
        self.quick_table.setStyleSheet("""
            QTableWidget {
                gridline-color: #d0d0d0;
            }
            QTableWidget::item {
                text-align: center;
                padding: 5px;
            }
        """)
        
        quick_layout.addWidget(self.quick_table)
        quick_view.setLayout(quick_layout)
        
        layout.addWidget(quick_view)
        
        layout.addStretch()
        
        widget.setLayout(layout)
        
        # Załaduj dane
        self.update_dashboard()
        
        return widget
    
    def create_history_tab(self):
        """Tworzy zakładkę Historia"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Filtry
        filter_layout = QHBoxLayout()
        
        filter_label = QLabel("Typ medium:")
        filter_label.setFont(QFont('Arial', 12, QFont.Bold))
        filter_layout.addWidget(filter_label)
        
        self.filter_utility_combo = QComboBox()
        self.filter_utility_combo.setFont(QFont('Arial', 12))
        self.filter_utility_combo.addItem("Wszystkie")
        self.filter_utility_combo.addItems(list(UTILITY_TYPES.keys()))
        self.filter_utility_combo.currentTextChanged.connect(self.update_history)
        filter_layout.addWidget(self.filter_utility_combo)
        
        filter_layout.addStretch()
        
        refresh_btn = QPushButton("🔄 Odśwież")
        refresh_btn.setFont(QFont('Arial', 12, QFont.Bold))
        refresh_btn.clicked.connect(self.update_history)
        filter_layout.addWidget(refresh_btn)
        
        layout.addLayout(filter_layout)
        
        # Tabela
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(5)
        self.history_table.setHorizontalHeaderLabels([
            "Data", "Medium", "Odczyt", "Zużycie", "Akcje"
        ])
        
        # Zwiększ czcionkę w tabeli
        self.history_table.setFont(QFont('Arial', 14))
        
        header = self.history_table.horizontalHeader()
        header.setFont(QFont('Arial', 16, QFont.Bold))
        # Kolumny równej szerokości (Stretch) - Data, Odczyt, Zużycie
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        # Medium - wąska kolumna (tylko tyle ile potrzeba)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        # Odczyt i Zużycie - równe z Data
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        # Akcje - wąska, tylko przyciski
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        
        # Zwiększ wysokość wierszy dla lepszej czytelności
        self.history_table.verticalHeader().setDefaultSectionSize(45)
        
        layout.addWidget(self.history_table)
        
        widget.setLayout(layout)
        
        # Załaduj dane
        self.update_history()
        
        return widget
    
    def create_charts_tab(self):
        """Tworzy zakładkę Wykresy"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        self.consumption_chart = ConsumptionChartWidget(self, self.db)
        layout.addWidget(self.consumption_chart)
        
        widget.setLayout(layout)
        
        return widget
    
    def create_analysis_tab(self):
        """Tworzy zakładkę Analiza"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        self.comparison_chart = ComparisonChartWidget(self, self.db)
        layout.addWidget(self.comparison_chart)
        
        widget.setLayout(layout)
        
        return widget
    
    def update_dashboard(self):
        """Aktualizuje dashboard"""
        # Aktualizuj statystyki
        for stats_widget in self.stats_widgets.values():
            stats_widget.update_stats()
        
        # Aktualizuj szybki podgląd
        self.update_quick_view()
    
    def update_quick_view(self):
        """Aktualizuje szybki podgląd"""
        self.quick_table.setRowCount(0)
        
        try:
            # Ostatnie 3 miesiące
            summary = self.db.get_utility_monthly_summary(3)
            
            for month_data in summary:
                row = self.quick_table.rowCount()
                self.quick_table.insertRow(row)
                
                # Miesiąc
                month_item = QTableWidgetItem(month_data['month_label'])
                month_item.setTextAlignment(Qt.AlignCenter)
                self.quick_table.setItem(row, 0, month_item)
                
                water = month_data.get('💧 Woda', {})
                electricity = month_data.get('⚡ Prąd', {})
                gas = month_data.get('🔥 Gaz', {})
                
                # Woda
                water_item = QTableWidgetItem(f"{water.get('consumption', 0):.1f} m³")
                water_item.setTextAlignment(Qt.AlignCenter)
                self.quick_table.setItem(row, 1, water_item)
                
                # Prąd
                elec_item = QTableWidgetItem(f"{electricity.get('consumption', 0):.1f} kWh")
                elec_item.setTextAlignment(Qt.AlignCenter)
                self.quick_table.setItem(row, 2, elec_item)
                
                # Gaz
                gas_item = QTableWidgetItem(f"{gas.get('consumption', 0):.1f} m³")
                gas_item.setTextAlignment(Qt.AlignCenter)
                self.quick_table.setItem(row, 3, gas_item)
                
        except Exception as e:
            logger.error(f"Błąd aktualizacji szybkiego podglądu: {e}")
    
    def update_history(self):
        """Aktualizuje historię odczytów"""
        self.history_table.setRowCount(0)
        
        filter_utility = self.filter_utility_combo.currentText()
        
        try:
            if filter_utility == "Wszystkie":
                readings = self.db.get_all_utility_readings()
            else:
                readings = self.db.get_utility_readings(filter_utility)
            
            for reading in readings:
                row = self.history_table.rowCount()
                self.history_table.insertRow(row)
                
                # Data
                date_item = QTableWidgetItem(reading['reading_date'])
                date_item.setTextAlignment(Qt.AlignCenter)
                self.history_table.setItem(row, 0, date_item)
                
                # Medium - BEZ KOLORÓW, wyśrodkowane
                utility_item = QTableWidgetItem(reading['utility_type'])
                utility_item.setTextAlignment(Qt.AlignCenter)
                self.history_table.setItem(row, 1, utility_item)
                
                # Odczyt - wyśrodkowany
                unit = UTILITY_TYPES.get(reading['utility_type'], {}).get('unit', '')
                reading_item = QTableWidgetItem(f"{reading['reading_value']:.2f} {unit}")
                reading_item.setTextAlignment(Qt.AlignCenter)
                self.history_table.setItem(row, 2, reading_item)
                
                # Zużycie - wyśrodkowane
                consumption_item = QTableWidgetItem(f"{reading['consumption']:.2f} {unit}")
                consumption_item.setTextAlignment(Qt.AlignCenter)
                self.history_table.setItem(row, 3, consumption_item)
                
                # Akcje
                actions_widget = QWidget()
                actions_layout = QHBoxLayout()
                actions_layout.setContentsMargins(2, 2, 2, 2)
                
                edit_btn = QPushButton("✏️")
                edit_btn.setMaximumWidth(35)
                edit_btn.clicked.connect(lambda checked, r=reading: self.edit_reading(r))
                actions_layout.addWidget(edit_btn)
                
                delete_btn = QPushButton("🗑️")
                delete_btn.setMaximumWidth(35)
                delete_btn.clicked.connect(lambda checked, r=reading: self.delete_reading(r))
                actions_layout.addWidget(delete_btn)
                
                actions_widget.setLayout(actions_layout)
                self.history_table.setCellWidget(row, 4, actions_widget)
                
        except Exception as e:
            logger.error(f"Błąd ładowania historii: {e}")
            QMessageBox.critical(self, "Błąd", f"Nie udało się załadować historii: {e}")
    
    def add_reading(self):
        """Dodaje nowy odczyt"""
        dialog = AddReadingDialog(self, self.db)
        
        if dialog.exec_() == QDialog.Accepted and dialog.result_data:
            data = dialog.result_data
            try:
                self.db.add_utility_reading(
                    data['utility_type'],
                    data['reading_date'],
                    data['reading_value'],
                    data['unit_cost'],
                    data['comment']
                )
                
                logger.info(f"Dodano odczyt: {data['utility_type']} - {data['reading_value']}")
                
                # Odśwież wszystkie widoki
                self.update_dashboard()
                self.update_history()
                
                if hasattr(self, 'consumption_chart'):
                    self.consumption_chart.update_chart()
                if hasattr(self, 'comparison_chart'):
                    self.comparison_chart.update_chart()
                
                QMessageBox.information(self, "Sukces", "✅ Odczyt został dodany!")
                
            except Exception as e:
                logger.error(f"Błąd dodawania odczytu: {e}")
                QMessageBox.critical(self, "Błąd", f"Nie udało się dodać odczytu:\n{e}")
    
    def edit_reading(self, reading):
        """Edytuje odczyt"""
        dialog = AddReadingDialog(self, self.db, reading['utility_type'], reading)
        
        if dialog.exec_() == QDialog.Accepted and dialog.result_data:
            data = dialog.result_data
            try:
                self.db.update_utility_reading(
                    data['id'],
                    data['reading_date'],
                    data['reading_value'],
                    data['unit_cost'],
                    data['comment']
                )
                
                logger.info(f"Zaktualizowano odczyt ID: {data['id']}")
                
                # Odśwież widoki
                self.update_dashboard()
                self.update_history()
                
                if hasattr(self, 'consumption_chart'):
                    self.consumption_chart.update_chart()
                if hasattr(self, 'comparison_chart'):
                    self.comparison_chart.update_chart()
                
                QMessageBox.information(self, "Sukces", "✅ Odczyt został zaktualizowany!")
                
            except Exception as e:
                logger.error(f"Błąd aktualizacji odczytu: {e}")
                QMessageBox.critical(self, "Błąd", f"Nie udało się zaktualizować odczytu:\n{e}")
    
    def delete_reading(self, reading):
        """Usuwa odczyt"""
        reply = QMessageBox.question(
            self,
            "Potwierdzenie",
            f"Czy na pewno usunąć odczyt z dnia {reading['reading_date']}?\n\n"
            f"Medium: {reading['utility_type']}\n"
            f"Wartość: {reading['reading_value']:.2f}",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                self.db.delete_utility_reading(reading['id'])
                
                logger.info(f"Usunięto odczyt ID: {reading['id']}")
                
                # Odśwież widoki
                self.update_dashboard()
                self.update_history()
                
                if hasattr(self, 'consumption_chart'):
                    self.consumption_chart.update_chart()
                if hasattr(self, 'comparison_chart'):
                    self.comparison_chart.update_chart()
                
                QMessageBox.information(self, "Sukces", "✅ Odczyt został usunięty!")
                
            except Exception as e:
                logger.error(f"Błąd usuwania odczytu: {e}")
                QMessageBox.critical(self, "Błąd", f"Nie udało się usunąć odczytu:\n{e}")
