# -*- coding: utf-8 -*-
"""
Moduł autoryzacji - zabezpieczenie aplikacji hasłem
- Master Password (bcrypt, 12 rounds)
- Recovery Key (format XXXX-XXXX-XXXX-XXXX)
- Rate limiting (5 prób, potem 15 min blokada)
- Auto-lock po bezczynności
"""

import secrets
import string
import logging
from datetime import datetime
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QLineEdit, QCheckBox, QMessageBox,
                             QTextEdit, QFormLayout, QGroupBox)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QIcon

logger = logging.getLogger(__name__)


class PasswordManager:
    """Menedżer haseł i recovery key"""
    
    @staticmethod
    def generate_recovery_key():
        """
        Generuje losowy recovery key w formacie: XXXX-XXXX-XXXX-XXXX
        32 znaki (bez myślników), używa uppercase liter i cyfr
        """
        chars = string.ascii_uppercase + string.digits
        # Usuń potencjalnie mylące znaki
        chars = chars.replace('O', '').replace('0', '').replace('I', '').replace('1', '')
        
        parts = []
        for _ in range(4):
            part = ''.join(secrets.choice(chars) for _ in range(4))
            parts.append(part)
        
        return '-'.join(parts)
    
    @staticmethod
    def validate_password_strength(password):
        """
        Waliduje siłę hasła
        Returns: (score, message) gdzie score: 0-4
        """
        if len(password) < 8:
            return 0, "Za krótkie (minimum 8 znaków)"
        
        score = 0
        feedback = []
        
        # Długość
        if len(password) >= 12:
            score += 1
            feedback.append("Dobra długość")
        elif len(password) >= 8:
            score += 0.5
        
        # Małe litery
        if any(c.islower() for c in password):
            score += 0.5
        
        # Wielkie litery
        if any(c.isupper() for c in password):
            score += 0.5
        
        # Cyfry
        if any(c.isdigit() for c in password):
            score += 0.5
            feedback.append("Zawiera cyfry")
        
        # Znaki specjalne
        if any(c in string.punctuation for c in password):
            score += 1
            feedback.append("Zawiera znaki specjalne")
        
        # Określ siłę
        if score >= 3.5:
            return 4, "Bardzo silne hasło ✓"
        elif score >= 2.5:
            return 3, "Silne hasło"
        elif score >= 1.5:
            return 2, "Średnie hasło"
        else:
            return 1, "Słabe hasło - dodaj cyfry i znaki specjalne"


class SetupPasswordDialog(QDialog):
    """Dialog pierwszej konfiguracji hasła"""
    
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.recovery_key = PasswordManager.generate_recovery_key()
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle('🔐 Zabezpieczenie aplikacji')
        self.setMinimumSize(600, 700)
        self.setModal(True)
        
        # Nieprzezroczyste tło
        self.setStyleSheet("""
            QDialog {
                background-color: #f3f4f6;
            }
        """)
        
        layout = QVBoxLayout()
        
        # Tytuł
        title = QLabel('🔐 USTAW HASŁO GŁÓWNE')
        title.setFont(QFont('Arial', 18, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #1f2937; margin: 20px;")
        layout.addWidget(title)
        
        # Opis
        desc = QLabel(
            'Zabezpiecz swoją aplikację master password.\n'
            'Hasło będzie wymagane przy każdym uruchomieniu.'
        )
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignCenter)
        desc.setStyleSheet("color: #6b7280; margin-bottom: 20px;")
        layout.addWidget(desc)
        
        # Formularz hasła
        password_group = QGroupBox("Hasło główne")
        password_layout = QFormLayout()
        
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setMinimumHeight(35)
        self.password_input.setPlaceholderText("Minimum 8 znaków")
        self.password_input.textChanged.connect(self.check_password_strength)
        password_layout.addRow("Nowe hasło:", self.password_input)
        
        self.password_confirm = QLineEdit()
        self.password_confirm.setEchoMode(QLineEdit.Password)
        self.password_confirm.setMinimumHeight(35)
        self.password_confirm.setPlaceholderText("Powtórz hasło")
        password_layout.addRow("Powtórz hasło:", self.password_confirm)
        
        # Wskaźnik siły hasła
        self.strength_label = QLabel("Siła hasła: -")
        self.strength_label.setStyleSheet("color: #6b7280; margin: 5px;")
        password_layout.addRow("", self.strength_label)
        
        # Pokaż hasło
        self.show_password_check = QCheckBox("Pokaż hasło")
        self.show_password_check.stateChanged.connect(self.toggle_password_visibility)
        password_layout.addRow("", self.show_password_check)
        
        password_group.setLayout(password_layout)
        layout.addWidget(password_group)
        
        # Recovery Key
        recovery_group = QGroupBox("⚠️ KLUCZ ODZYSKIWANIA (Recovery Key)")
        recovery_layout = QVBoxLayout()
        
        recovery_info = QLabel(
            "Ten klucz pozwoli Ci odzyskać dostęp w przypadku zapomnienia hasła.\n"
            "MUSISZ go zapisać w bezpiecznym miejscu!"
        )
        recovery_info.setWordWrap(True)
        recovery_info.setStyleSheet("color: #dc2626; margin: 10px; font-weight: bold;")
        recovery_layout.addWidget(recovery_info)
        
        # Wyświetl recovery key
        self.recovery_display = QTextEdit()
        self.recovery_display.setReadOnly(True)
        self.recovery_display.setMaximumHeight(60)
        self.recovery_display.setPlainText(self.recovery_key)
        self.recovery_display.setStyleSheet("""
            QTextEdit {
                background-color: #fef3c7;
                border: 2px solid #f59e0b;
                border-radius: 5px;
                padding: 10px;
                font-size: 16px;
                font-weight: bold;
                font-family: 'Courier New', monospace;
                color: #92400e;
            }
        """)
        recovery_layout.addWidget(self.recovery_display)
        
        # Przyciski akcji dla recovery key
        recovery_buttons = QHBoxLayout()
        
        copy_btn = QPushButton('📋 Kopiuj do schowka')
        copy_btn.clicked.connect(self.copy_recovery_key)
        copy_btn.setMinimumHeight(35)
        recovery_buttons.addWidget(copy_btn)
        
        print_btn = QPushButton('🖨️ Drukuj')
        print_btn.clicked.connect(self.print_recovery_key)
        print_btn.setMinimumHeight(35)
        recovery_buttons.addWidget(print_btn)
        
        recovery_layout.addLayout(recovery_buttons)
        
        # Checkbox potwierdzenia
        self.confirm_saved = QCheckBox(
            "✓ Potwierdzam, że zapisałem Recovery Key w bezpiecznym miejscu"
        )
        self.confirm_saved.setStyleSheet("margin: 10px; font-weight: bold;")
        recovery_layout.addWidget(self.confirm_saved)
        
        recovery_group.setLayout(recovery_layout)
        layout.addWidget(recovery_group)
        
        # Dodatkowe opcje
        options_group = QGroupBox("Opcje zabezpieczeń")
        options_layout = QVBoxLayout()
        
        self.auto_lock_check = QCheckBox("Włącz automatyczną blokadę po 30 minutach bezczynności")
        self.auto_lock_check.setChecked(False)
        options_layout.addWidget(self.auto_lock_check)
        
        options_group.setLayout(options_layout)
        layout.addWidget(options_group)
        
        layout.addStretch()
        
        # Przyciski
        buttons_layout = QHBoxLayout()
        
        cancel_btn = QPushButton('Anuluj')
        cancel_btn.setMinimumHeight(45)
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #6b7280;
                color: white;
                border-radius: 8px;
                padding: 10px 20px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #4b5563;
            }
        """)
        buttons_layout.addWidget(cancel_btn)
        
        self.save_btn = QPushButton('💾 Zapisz i zabezpiecz')
        self.save_btn.setMinimumHeight(45)
        self.save_btn.clicked.connect(self.save_password)
        self.save_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                border-radius: 8px;
                padding: 10px 20px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        buttons_layout.addWidget(self.save_btn)
        
        layout.addLayout(buttons_layout)
        
        self.setLayout(layout)
    
    def check_password_strength(self):
        """Sprawdza siłę hasła"""
        password = self.password_input.text()
        
        if not password:
            self.strength_label.setText("Siła hasła: -")
            self.strength_label.setStyleSheet("color: #6b7280;")
            return
        
        score, message = PasswordManager.validate_password_strength(password)
        
        # Kolory dla różnych poziomów
        colors = {
            0: "#dc2626",  # Czerwony
            1: "#f59e0b",  # Pomarańczowy
            2: "#eab308",  # Żółty
            3: "#10b981",  # Zielony
            4: "#059669"   # Ciemnozielony
        }
        
        self.strength_label.setText(f"Siła hasła: {message}")
        self.strength_label.setStyleSheet(f"color: {colors[score]}; font-weight: bold;")
    
    def toggle_password_visibility(self, state):
        """Przełącza widoczność hasła"""
        if state == Qt.Checked:
            self.password_input.setEchoMode(QLineEdit.Normal)
            self.password_confirm.setEchoMode(QLineEdit.Normal)
        else:
            self.password_input.setEchoMode(QLineEdit.Password)
            self.password_confirm.setEchoMode(QLineEdit.Password)
    
    def copy_recovery_key(self):
        """Kopiuje recovery key do schowka"""
        from PyQt5.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(self.recovery_key)
        
        QMessageBox.information(
            self,
            'Skopiowano',
            'Recovery Key został skopiowany do schowka.\n\n'
            'Wklej go do bezpiecznego miejsca (np. menedżer haseł, plik tekstowy).'
        )
    
    def print_recovery_key(self):
        """Drukuje recovery key"""
        QMessageBox.information(
            self,
            'Drukowanie',
            'Funkcja drukowania zostanie zaimplementowana w przyszłej wersji.\n\n'
            'Na razie skopiuj klucz ręcznie lub użyj funkcji "Kopiuj do schowka".'
        )
    
    def save_password(self):
        """Zapisuje hasło i recovery key"""
        password = self.password_input.text()
        confirm = self.password_confirm.text()
        
        # Walidacja
        if not password:
            QMessageBox.warning(self, 'Błąd', 'Wprowadź hasło!')
            return
        
        if len(password) < 8:
            QMessageBox.warning(self, 'Błąd', 'Hasło musi mieć minimum 8 znaków!')
            return
        
        if password != confirm:
            QMessageBox.warning(self, 'Błąd', 'Hasła nie są identyczne!')
            return
        
        if not self.confirm_saved.isChecked():
            QMessageBox.warning(
                self,
                'Uwaga',
                'Musisz potwierdzić, że zapisałeś Recovery Key!\n\n'
                'Bez tego klucza nie będziesz mógł odzyskać dostępu w przypadku zapomnienia hasła.'
            )
            return
        
        try:
            # Zapisz hasło i recovery key w bazie
            self.db.create_password(password, self.recovery_key)
            
            # Ustaw auto-lock jeśli zaznaczono
            if self.auto_lock_check.isChecked():
                self.db.set_setting('auto_lock_enabled', 'true')
            
            QMessageBox.information(
                self,
                'Sukces',
                'Hasło zostało ustawione pomyślnie!\n\n'
                'Od teraz aplikacja będzie wymagać hasła przy uruchomieniu.'
            )
            
            self.accept()
            
        except Exception as e:
            logger.error(f"Błąd zapisywania hasła: {e}")
            QMessageBox.critical(
                self,
                'Błąd',
                f'Nie udało się zapisać hasła:\n{str(e)}'
            )


class LoginDialog(QDialog):
    """Dialog logowania"""
    
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle('🔒 Wymagane hasło')
        self.setMinimumSize(550, 500)  # Zwiększony rozmiar dla bannera ostrzegawczego
        self.setModal(True)
        
        # Przycisk X ma zamykać aplikację (nie usuwamy go)
        
        # Nieprzezroczyste tło - żeby nie było widać pulpitu
        self.setStyleSheet("""
            QDialog {
                background-color: #f3f4f6;
            }
        """)
        
        layout = QVBoxLayout()
        
        # Logo/Tytuł
        title = QLabel('💵 WALLET 💵')
        title.setFont(QFont('Arial', 26, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #059669; margin: 30px 20px;")
        layout.addWidget(title)
        
        # ============================================================
        # OSTRZEŻENIE O NIEAUTORYZOWANYM DOSTĘPIE
        # ============================================================
        warning_frame = QLabel()
        warning_frame.setWordWrap(True)
        warning_frame.setAlignment(Qt.AlignCenter)
        warning_frame.setText(
            "⚠️ OSTRZEŻENIE ⚠️\n\n"
            "Ten system jest przeznaczony wyłącznie dla osób autoryzowanych.\n"
            "Nieautoryzowany dostęp lub użycie tego systemu jest surowo zabronione\n"
            "i może podlegać sankcjom karnym i cywilnym.\n\n"
            "Wszystkie aktywności w tym systemie są monitorowane i rejestrowane.\n"
            "Kontynuując, potwierdzasz i zgadzasz się na ten monitoring."
        )
        warning_frame.setStyleSheet("""
            QLabel {
                background-color: #fef3c7;
                border: 2px solid #f59e0b;
                border-radius: 8px;
                padding: 15px;
                margin: 10px 20px;
                color: #92400e;
                font-size: 14px;
                font-weight: bold;
                line-height: 1.5;
            }
        """)
        layout.addWidget(warning_frame)
        
        subtitle = QLabel('Wprowadź hasło, aby odblokować aplikację')
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #6b7280; margin-bottom: 20px; margin-top: 15px;")
        layout.addWidget(subtitle)
        
        # Pole hasła
        password_layout = QHBoxLayout()
        password_layout.addStretch()
        
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("Hasło")
        self.password_input.setMinimumWidth(300)
        self.password_input.setMinimumHeight(45)
        self.password_input.setStyleSheet("""
            QLineEdit {
                border: 2px solid #d1d5db;
                border-radius: 8px;
                padding: 10px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 2px solid #10b981;
            }
        """)
        self.password_input.returnPressed.connect(self.login)
        password_layout.addWidget(self.password_input)
        
        password_layout.addStretch()
        layout.addLayout(password_layout)
        
        # Przycisk odblokuj
        unlock_layout = QHBoxLayout()
        unlock_layout.addStretch()
        
        unlock_btn = QPushButton('🔓 Odblokuj')
        unlock_btn.setMinimumWidth(300)
        unlock_btn.setMinimumHeight(45)
        unlock_btn.clicked.connect(self.login)
        unlock_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                border-radius: 8px;
                padding: 10px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        unlock_layout.addWidget(unlock_btn)
        
        unlock_layout.addStretch()
        layout.addLayout(unlock_layout)
        
        layout.addStretch()
        
        # Link do recovery
        recovery_layout = QHBoxLayout()
        recovery_layout.addStretch()
        
        recovery_link = QLabel('<a href="#" style="color: #3b82f6;">🔑 Zapomniałeś hasła? Użyj Recovery Key</a>')
        recovery_link.setOpenExternalLinks(False)
        recovery_link.linkActivated.connect(self.show_recovery_dialog)
        recovery_link.setAlignment(Qt.AlignCenter)
        recovery_layout.addWidget(recovery_link)
        
        recovery_layout.addStretch()
        layout.addLayout(recovery_layout)
        
        # Komunikat o błędzie
        self.error_label = QLabel('')
        self.error_label.setAlignment(Qt.AlignCenter)
        self.error_label.setStyleSheet("color: #dc2626; margin: 10px; font-weight: bold;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        
        layout.addSpacing(20)
        
        self.setLayout(layout)
        
        # Focus na pole hasła
        self.password_input.setFocus()
    
    def login(self):
        """Próba logowania"""
        password = self.password_input.text()
        
        if not password:
            self.error_label.setText('Wprowadź hasło!')
            return
        
        success, message = self.db.verify_password(password)
        
        if success:
            self.accept()
        else:
            self.error_label.setText(message)
            self.password_input.clear()
            self.password_input.setFocus()
    
    def show_recovery_dialog(self):
        """Pokazuje dialog odzyskiwania hasła"""
        dialog = RecoveryDialog(self.db, self)
        if dialog.exec_() == QDialog.Accepted:
            # Hasło zostało zresetowane - zamknij dialog logowania
            self.accept()
    
    def closeEvent(self, event):
        """Obsługuje zamknięcie okna przez przycisk X"""
        # Kliknięcie X = zamknięcie aplikacji (nie logujemy się)
        import sys
        sys.exit(0)


class RecoveryDialog(QDialog):
    """Dialog odzyskiwania hasła przez Recovery Key"""
    
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle('🔑 Odzyskiwanie dostępu')
        self.setMinimumSize(550, 500)
        self.setModal(True)
        
        # Nieprzezroczyste tło
        self.setStyleSheet("""
            QDialog {
                background-color: #f3f4f6;
            }
        """)
        
        layout = QVBoxLayout()
        
        # Tytuł
        title = QLabel('🔑 ODZYSKIWANIE HASŁA')
        title.setFont(QFont('Arial', 18, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #1f2937; margin: 20px;")
        layout.addWidget(title)
        
        # Instrukcja
        instruction = QLabel(
            'Wprowadź Recovery Key, który został wygenerowany podczas\n'
            'konfiguracji hasła, aby ustawić nowe hasło.'
        )
        instruction.setWordWrap(True)
        instruction.setAlignment(Qt.AlignCenter)
        instruction.setStyleSheet("color: #6b7280; margin-bottom: 20px;")
        layout.addWidget(instruction)
        
        # Recovery Key
        recovery_group = QGroupBox("Recovery Key")
        recovery_layout = QFormLayout()
        
        self.recovery_input = QLineEdit()
        self.recovery_input.setPlaceholderText("XXXX-XXXX-XXXX-XXXX")
        self.recovery_input.setMinimumHeight(40)
        self.recovery_input.setMaxLength(19)  # 16 znaków + 3 myślniki
        recovery_layout.addRow("Klucz:", self.recovery_input)
        
        recovery_group.setLayout(recovery_layout)
        layout.addWidget(recovery_group)
        
        # Nowe hasło
        password_group = QGroupBox("Nowe hasło")
        password_layout = QFormLayout()
        
        self.new_password = QLineEdit()
        self.new_password.setEchoMode(QLineEdit.Password)
        self.new_password.setMinimumHeight(40)
        self.new_password.setPlaceholderText("Minimum 8 znaków")
        password_layout.addRow("Nowe hasło:", self.new_password)
        
        self.new_password_confirm = QLineEdit()
        self.new_password_confirm.setEchoMode(QLineEdit.Password)
        self.new_password_confirm.setMinimumHeight(40)
        password_layout.addRow("Powtórz:", self.new_password_confirm)
        
        password_group.setLayout(password_layout)
        layout.addWidget(password_group)
        
        layout.addStretch()
        
        # Przyciski
        buttons_layout = QHBoxLayout()
        
        cancel_btn = QPushButton('Anuluj')
        cancel_btn.setMinimumHeight(45)
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #6b7280;
                color: white;
                border-radius: 8px;
                padding: 10px 20px;
            }
            QPushButton:hover {
                background-color: #4b5563;
            }
        """)
        buttons_layout.addWidget(cancel_btn)
        
        reset_btn = QPushButton('💾 Ustaw nowe hasło')
        reset_btn.setMinimumHeight(45)
        reset_btn.clicked.connect(self.reset_password)
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                border-radius: 8px;
                padding: 10px 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        buttons_layout.addWidget(reset_btn)
        
        layout.addLayout(buttons_layout)
        
        self.setLayout(layout)
    
    def reset_password(self):
        """Resetuje hasło używając recovery key"""
        recovery_key = self.recovery_input.text().strip()
        new_password = self.new_password.text()
        confirm = self.new_password_confirm.text()
        
        # Walidacja
        if not recovery_key:
            QMessageBox.warning(self, 'Błąd', 'Wprowadź Recovery Key!')
            return
        
        if not new_password:
            QMessageBox.warning(self, 'Błąd', 'Wprowadź nowe hasło!')
            return
        
        if len(new_password) < 8:
            QMessageBox.warning(self, 'Błąd', 'Hasło musi mieć minimum 8 znaków!')
            return
        
        if new_password != confirm:
            QMessageBox.warning(self, 'Błąd', 'Hasła nie są identyczne!')
            return
        
        # Weryfikuj recovery key
        if not self.db.verify_recovery_key(recovery_key):
            QMessageBox.critical(
                self,
                'Błąd',
                'Nieprawidłowy Recovery Key!\n\n'
                'Upewnij się, że wpisałeś prawidłowy klucz.'
            )
            return
        
        try:
            # Generuj nowy recovery key
            new_recovery_key = PasswordManager.generate_recovery_key()
            
            # Zmień hasło
            self.db.change_password(new_password, new_recovery_key)
            
            # Pokaż nowy recovery key
            QMessageBox.information(
                self,
                'Sukces',
                f'Hasło zostało zmienione!\n\n'
                f'WAŻNE: Nowy Recovery Key:\n'
                f'{new_recovery_key}\n\n'
                f'Zapisz go w bezpiecznym miejscu!'
            )
            
            self.accept()
            
        except Exception as e:
            logger.error(f"Błąd resetowania hasła: {e}")
            QMessageBox.critical(
                self,
                'Błąd',
                f'Nie udało się zresetować hasła:\n{str(e)}'
            )


class ChangePasswordDialog(QDialog):
    """Dialog zmiany hasła (z ustawień)"""
    
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle('🔑 Zmiana hasła')
        self.setMinimumSize(500, 450)
        self.setModal(True)
        
        # Nieprzezroczyste tło
        self.setStyleSheet("""
            QDialog {
                background-color: #f3f4f6;
            }
        """)
        
        layout = QVBoxLayout()
        
        # Tytuł
        title = QLabel('🔑 ZMIANA HASŁA')
        title.setFont(QFont('Arial', 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #1f2937; margin: 20px;")
        layout.addWidget(title)
        
        # Formularz
        form_layout = QFormLayout()
        
        self.current_password = QLineEdit()
        self.current_password.setEchoMode(QLineEdit.Password)
        self.current_password.setMinimumHeight(35)
        form_layout.addRow("Obecne hasło:", self.current_password)
        
        self.new_password = QLineEdit()
        self.new_password.setEchoMode(QLineEdit.Password)
        self.new_password.setMinimumHeight(35)
        form_layout.addRow("Nowe hasło:", self.new_password)
        
        self.new_password_confirm = QLineEdit()
        self.new_password_confirm.setEchoMode(QLineEdit.Password)
        self.new_password_confirm.setMinimumHeight(35)
        form_layout.addRow("Powtórz hasło:", self.new_password_confirm)
        
        layout.addLayout(form_layout)
        
        # Opcja nowego recovery key
        self.generate_new_key = QCheckBox("Wygeneruj nowy Recovery Key")
        self.generate_new_key.setChecked(True)
        self.generate_new_key.setStyleSheet("margin: 20px 10px;")
        layout.addWidget(self.generate_new_key)
        
        layout.addStretch()
        
        # Przyciski
        buttons_layout = QHBoxLayout()
        
        cancel_btn = QPushButton('Anuluj')
        cancel_btn.setMinimumHeight(40)
        cancel_btn.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_btn)
        
        save_btn = QPushButton('💾 Zmień hasło')
        save_btn.setMinimumHeight(40)
        save_btn.clicked.connect(self.change_password)
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                border-radius: 8px;
                padding: 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        buttons_layout.addWidget(save_btn)
        
        layout.addLayout(buttons_layout)
        
        self.setLayout(layout)
    
    def change_password(self):
        """Zmienia hasło"""
        current = self.current_password.text()
        new = self.new_password.text()
        confirm = self.new_password_confirm.text()
        
        # Walidacja
        if not current:
            QMessageBox.warning(self, 'Błąd', 'Wprowadź obecne hasło!')
            return
        
        if not new:
            QMessageBox.warning(self, 'Błąd', 'Wprowadź nowe hasło!')
            return
        
        if len(new) < 8:
            QMessageBox.warning(self, 'Błąd', 'Nowe hasło musi mieć minimum 8 znaków!')
            return
        
        if new != confirm:
            QMessageBox.warning(self, 'Błąd', 'Nowe hasła nie są identyczne!')
            return
        
        # Weryfikuj obecne hasło
        success, message = self.db.verify_password(current)
        if not success:
            QMessageBox.critical(self, 'Błąd', f'Nieprawidłowe obecne hasło!\n{message}')
            return
        
        try:
            new_recovery_key = None
            
            if self.generate_new_key.isChecked():
                new_recovery_key = PasswordManager.generate_recovery_key()
            
            # Zmień hasło
            self.db.change_password(new, new_recovery_key)
            
            if new_recovery_key:
                QMessageBox.information(
                    self,
                    'Sukces',
                    f'Hasło zostało zmienione!\n\n'
                    f'NOWY Recovery Key:\n'
                    f'{new_recovery_key}\n\n'
                    f'Zapisz go w bezpiecznym miejscu!'
                )
            else:
                QMessageBox.information(
                    self,
                    'Sukces',
                    'Hasło zostało zmienione!\n\n'
                    'Recovery Key pozostał bez zmian.'
                )
            
            self.accept()
            
        except Exception as e:
            logger.error(f"Błąd zmiany hasła: {e}")
            QMessageBox.critical(
                self,
                'Błąd',
                f'Nie udało się zmienić hasła:\n{str(e)}'
            )
