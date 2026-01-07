# 💵 WALLET - Aplikacja do Zarządzania Portfolio i Budżetem

![Python](https://img.shields.io/badge/python-3.8+-blue.svg)
![Licencja](https://img.shields.io/badge/licencja-MIT-green.svg)
![Platforma](https://img.shields.io/badge/platforma-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)

**WALLET** to darmowa aplikacja desktopowa open-source do zarządzania portfelem inwestycyjnym, budżetem domowym i śledzeniem mediów. Zbudowana w Python + PyQt5, działa całkowicie offline z danymi przechowywanymi lokalnie.

[🇬🇧 English Version](README.md) | [📸 Zrzuty ekranu](#zrzuty-ekranu) | [🚀 Szybki start](#szybki-start)

---

## 🌟 Funkcje

### 📊 Zarządzanie Portfolio
- Obsługa wielu walut (USD/PLN z automatycznymi kursami)
- Aktualizacja cen w czasie rzeczywistym (Yahoo Finance)
- Automatyczne obliczanie zysków/strat
- Historia transakcji
- Watchlista z 4-poziomowymi alertami cenowymi (HP1-HP4)
- System strategii inwestycyjnych
- Eksport/Import danych

### 💰 Moduł Budżetu
- Śledzenie przychodów
- Kategoryzacja wydatków
- Zarządzanie wydatkami cyklicznymi
- Miesięczne podsumowania i wykresy

### 📊 Śledzenie Mediów
- Monitorowanie zużycia wody, prądu, gazu
- Dane historyczne i trendy
- Kalkulacja kosztów

### 🔒 Bezpieczeństwo
- Ochrona hasłem (szyfrowanie bcrypt)
- Rate limiting (5 prób / 15 minut)
- Auto-blokada po bezczynności
- Integracja z blokowaniem Windows (Win+L)
- System klucza odzyskiwania
- Opcja manualnego wylogowania

---

## 📸 Zrzuty ekranu

### Widok Portfolio
![Portfolio](docs/screenshots/portfolio.png)

### Moduł Budżetu
![Budżet](docs/screenshots/budget.png)

### Logowanie
![Login](docs/screenshots/login.png)

---

## 🎯 Po co ta aplikacja?

Aplikacja została stworzona aby rozwiązać kilka problemów:

�?**Brak limitów Excela** - Pełna automatyzacja, integracja API, profesjonalny UI  
�?**Brak zależności od chmury** - Wszystkie dane lokalnie, działa offline  
�?**Przenośna** - Uruchom z pendrive, nie wymaga instalacji  
�?**Open source** - Pełna kontrola, modyfikuj jak potrzebujesz  
�?**Rozwój z pomocą AI** - Zbudowana z Claude AI (Anthropic) jako proof of concept  

---

## 🚀 Szybki start

### Wymagania
- Python 3.8 lub wyższy
- Windows 10/11, Linux, lub macOS

### Instalacja

```bash
# Sklonuj repozytorium
git clone https://github.com/kzaklikiewicz/wallet-app.git
cd wallet-app

# Zainstaluj zależności
pip install -r requirements.txt

# Uruchom aplikację
python portfolio_app.py
```

### Pierwsze uruchomienie
1. Aplikacja automatycznie tworzy `portfolio.db`
2. Opcjonalnie ustaw ochronę hasłem w Ustawieniach
3. Zacznij dodawać pozycje lub korzystaj z modułu budżetu

---

## 📦 Wymagania

```
PyQt5>=5.15.0
yfinance>=0.2.0
pandas>=1.5.0
requests>=2.28.0
bcrypt>=4.0.0
pywin32>=305 (tylko Windows)
```

---

## 🔧 Konfiguracja

### Włączanie ochrony hasłem
1. Przejdź do **Ustawienia** �?**Zabezpieczenia**
2. Kliknij **Ustaw hasło**
3. Zapisz swój **Klucz odzyskiwania** (XXXX-XXXX-XXXX-XXXX)
4. Opcjonalnie: Włącz **Auto-Lock** i **Integrację z Windows**

### Lokalizacja bazy danych
Domyślnie `portfolio.db` jest tworzony w katalogu aplikacji. Możesz go przenieść w dowolne miejsce (pendrive, zaszyfrowany folder, etc.).

---

## 🏗�?Architektura

```
wallet-app/
├── portfolio_app.py      # Główna aplikacja
├── database.py           # Warstwa bazy danych (SQLite)
├── auth_module.py        # System autoryzacji
├── budget_module.py      # Funkcjonalność budżetu
├── media_module.py       # Śledzenie mediów
├── requirements.txt      # Zależności
├── portfolio.db          # Baza SQLite (tworzona przy pierwszym uruchomieniu)
└── Logs/                 # Logi aplikacji
```

---

## 🔒 Bezpieczeństwo

### Co jest chronione
�?Dostęp do UI (wymagane hasło)  
�?Hasła (bcrypt z 12 rundami)  
�?Klucze odzyskiwania (zahashowane bcrypt)  
�?Rate limiting (ochrona przed brute-force)  
�?Auto-blokada przy bezczynności  
�?Integracja z sesjami Windows  

### Co NIE jest chronione
�?Plik bazy danych (`portfolio.db`) **NIE jest zaszyfrowany**  
�?Każdy z dostępem do pliku może odczytać dane przez SQLite Browser  

### Rekomendacje
- Użyj **BitLocker** (Windows) lub **FileVault** (macOS) do szyfrowania całego dysku
- Rozważ użycie **SQLCipher** do szyfrowania bazy (zaawansowane)
- Przechowuj Klucz Odzyskiwania bezpiecznie (menedżer haseł, sejf, etc.)

**Pełny raport bezpieczeństwa:** [SECURITY.md](SECURITY.md)

---

## 🎨 Dostosowywanie

Aplikacja jest zaprojektowana tak aby łatwo ją modyfikować:

### Zmiana kolorów
Edytuj style CSS w `portfolio_app.py`:
```python
self.settings_btn.setStyleSheet("""
    QPushButton {
        background-color: #6b7280;  # Zmień to
        color: white;
    }
""")
```

### Dodawanie nowych funkcji
1. Zmodyfikuj schemat bazy w `database.py`
2. Dodaj komponenty UI w `portfolio_app.py`
3. Połącz sygnały ze slotami

### Stwórz własny moduł
Podążaj za strukturą `budget_module.py` lub `media_module.py`

---

## 📊 Wydajność

- **Czas startu:** < 2 sekundy
- **Ładowanie portfolio:** Instant (hybrydowy system cache)
- **Odświeżanie cen:** 100+ tickerów w < 10 sekund (pobieranie wsadowe)
- **Rozmiar bazy:** ~2-5 MB dla typowego użycia
- **Użycie pamięci:** ~150-200 MB

---

## 🐛 Rozwiązywanie problemów

### "No module named 'PyQt5'"
```bash
pip install PyQt5
```

### "No module named 'win32api'" (Windows)
```bash
pip install pywin32
```

### Błąd zablokowanej bazy danych
Zamknij wszystkie instancje aplikacji i spróbuj ponownie.

### Ceny się nie aktualizują
Sprawdź połączenie z internetem i ustawienia firewall (wymagany dostęp do Yahoo Finance API).

---

## 🤝 Współpraca

Wkład w projekt jest mile widziany! Zobacz [CONTRIBUTING.md](CONTRIBUTING.md) dla wytycznych.

### Jak współpracować
1. Zrób fork repozytorium
2. Stwórz branch z feature (`git checkout -b feature/amazing-feature`)
3. Zatwierdź zmiany (`git commit -m 'Dodaj amazing feature'`)
4. Wypchnij branch (`git push origin feature/amazing-feature`)
5. Otwórz Pull Request

---

## 📝 Licencja

Ten projekt jest licencjonowany na **Licencji MIT** - zobacz plik [LICENSE](LICENSE) dla szczegółów.

**W skrócie:** Możesz używać, modyfikować, dystrybuować, a nawet sprzedawać to oprogramowanie. Bez ograniczeń, bez gwarancji.

---

## 🙏 Podziękowania

- **Claude AI (Anthropic)** - Asystent AI który pomógł zbudować tę aplikację
- **yfinance** - Wrapper Yahoo Finance API
- **PyQt5** - Framework GUI
- **Społeczność** - Wszyscy kontrybutorzy i użytkownicy

---

## 📞 Kontakt i wsparcie

- **Problemy:** [GitHub Issues](https://github.com/kzaklikiewicz/wallet-app/issues)
- **Dyskusje:** [GitHub Discussions](https://github.com/kzaklikiewicz/wallet-app/discussions)
- **Email:** your.email@example.com

---

## 🗺�?Plan rozwoju

### Wersja 3.2 (Planowana)
- [ ] Szyfrowanie bazy danych (SQLCipher)
- [ ] Eksport do Excel
- [ ] Więcej typów wykresów
- [ ] Aplikacja mobilna (companion)

### Wersja 4.0 (Przyszłość)
- [ ] Obsługa wielu użytkowników
- [ ] Sync w chmurze (opcjonalny)
- [ ] Zaawansowana analityka
- [ ] Narzędzia optymalizacji portfolio

---

## �?Historia gwiazdek

Jeśli projekt jest dla Ciebie użyteczny, rozważ danie gwiazdki! �?
---

## 📜 Historia zmian

Zobacz [CHANGELOG.md](CHANGELOG.md) dla historii wersji.

---

## 🎓 Materiały edukacyjne

Ten projekt został zbudowany jako demonstracja:
- Rozwoju oprogramowania z pomocą AI
- Architektury aplikacji desktopowych PyQt5
- Projektowania baz danych SQLite
- Integracji API danych finansowych
- Najlepszych praktyk bezpieczeństwa

Możesz go używać jako materiału do nauki!

---

**Stworzone z ❤️ i pomocą AI (Claude by Anthropic)**

**Status:** �?Gotowe do produkcji | 🔄 Aktywnie utrzymywane | 📖 Dobrze udokumentowane
