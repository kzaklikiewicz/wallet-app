# 📦 Instrukcja Instalacji Zależności

## 🚀 Szybka Instalacja (Zalecana)

### Opcja 1: Podstawowa instalacja
```bash
pip install -r requirements.txt
```

### Opcja 2: Minimalna (bez komentarzy)
```bash
pip install -r requirements-minimal.txt
```

### Opcja 3: Wersje przetestowane (najbezpieczniejsze)
```bash
pip install -r requirements-pinned.txt
```

---

## 🔧 Instalacja Krok po Kroku

### 1. Sprawdź wersję Pythona
```bash
python --version
# Wymagane: Python 3.8 lub wyższy
```

### 2. Utwórz virtual environment (ZALECANE!)
```bash
# Windows:
python -m venv venv
venv\Scripts\activate

# Linux/Mac:
python3 -m venv venv
source venv/bin/activate
```

### 3. Zaktualizuj pip
```bash
python -m pip install --upgrade pip
```

### 4. Zainstaluj zależności
```bash
pip install -r requirements.txt
```

### 5. Sprawdź instalację
```bash
pip list
# Powinieneś zobaczyć wszystkie zainstalowane pakiety
```

---

## 📋 Lista Pakietów

| Pakiet | Wersja | Rozmiar | Przeznaczenie |
|--------|--------|---------|---------------|
| PyQt5 | ≥5.15.0 | ~50 MB | GUI Framework |
| yfinance | ≥0.2.0 | ~2 MB | Yahoo Finance API |
| pandas | ≥1.5.0 | ~15 MB | Data manipulation |
| numpy | ≥1.24.0 | ~20 MB | Numerical operations |
| requests | ≥2.28.0 | ~500 KB | HTTP requests |
| bcrypt | ≥4.0.0 | ~100 KB | Password hashing |
| matplotlib | ≥3.7.0 | ~30 MB | Charts & plots |
| pywin32 | ≥305 | ~10 MB | Windows API (Windows only) |

**Całkowity rozmiar:** ~130 MB

---

## 🐛 Rozwiązywanie Problemów

### Problem: PyQt5 nie instaluje się

**Rozwiązanie 1:**
```bash
pip install PyQt5 --no-cache-dir
```

**Rozwiązanie 2 (Windows):**
```bash
pip install PyQt5-Qt5
pip install PyQt5
```

**Rozwiązanie 3 (Linux):**
```bash
sudo apt-get install python3-pyqt5
# Lub zainstaluj bez pip:
pip install --no-binary PyQt5 PyQt5
```

---

### Problem: matplotlib nie instaluje się (Windows)

**Rozwiązanie:**
1. Zainstaluj Microsoft C++ Build Tools
2. Pobierz z: https://visualstudio.microsoft.com/visual-cpp-build-tools/
3. Wybierz "Desktop development with C++"
4. Następnie: `pip install matplotlib`

---

### Problem: pywin32 nie instaluje się (Windows)

**Rozwiązanie:**
```bash
python -m pip install --upgrade pywin32
python Scripts\pywin32_postinstall.py -install
```

---

### Problem: numpy nie instaluje się

**Rozwiązanie:**
```bash
pip install numpy --upgrade
# Lub:
pip install numpy --pre --upgrade
```

---

### Problem: "Permission denied" podczas instalacji

**Rozwiązanie 1 (Windows):**
- Uruchom CMD/PowerShell jako Administrator

**Rozwiązanie 2 (Linux/Mac):**
```bash
pip install --user -r requirements.txt
```

---

### Problem: Konflikt wersji

**Rozwiązanie:**
```bash
# Usuń wszystkie pakiety i zainstaluj od nowa
pip freeze > to_remove.txt
pip uninstall -r to_remove.txt -y
pip install -r requirements.txt
```

---

## 🌍 Instalacja Specyficzna dla Platformy

### Windows 10/11
```bash
# Instalacja standardowa - wszystko powinno działać
pip install -r requirements.txt

# Jeśli problemy z PyQt5:
pip install PyQt5 --no-cache-dir
```

### Linux (Ubuntu/Debian)
```bash
# Zainstaluj dodatkowe zależności systemowe
sudo apt-get update
sudo apt-get install python3-dev python3-pip
sudo apt-get install python3-pyqt5

# Następnie:
pip install -r requirements.txt
```

### macOS
```bash
# Jeśli masz Homebrew:
brew install python-tk
brew install pyqt5

# Następnie:
pip install -r requirements.txt
```

---

## ✅ Weryfikacja Instalacji

### Test 1: Sprawdź importy
```bash
python -c "import PyQt5; print('PyQt5: OK')"
python -c "import yfinance; print('yfinance: OK')"
python -c "import pandas; print('pandas: OK')"
python -c "import bcrypt; print('bcrypt: OK')"
python -c "import matplotlib; print('matplotlib: OK')"
```

### Test 2: Uruchom aplikację
```bash
python portfolio_app.py
# Jeśli okno się otwiera - instalacja OK!
```

---

## 🔄 Aktualizacja Pakietów

### Aktualizuj wszystkie pakiety
```bash
pip install -r requirements.txt --upgrade
```

### Aktualizuj pojedynczy pakiet
```bash
pip install yfinance --upgrade
```

### Sprawdź dostępne aktualizacje
```bash
pip list --outdated
```

---

## 💾 Export Zainstalowanych Wersji

Jeśli chcesz zapisać DOKŁADNIE to co masz zainstalowane:

```bash
pip freeze > my-requirements.txt
```

---

## 🆘 Dalsze Wsparcie

Jeśli nadal masz problemy:

1. **GitHub Issues:** https://github.com/YOUR_USERNAME/wallet-app/issues
2. **Stack Overflow:** Tag `pyqt5` lub `python`
3. **Python Discord:** https://discord.gg/python

---

## 📖 Dodatkowe Materiały

- **PyQt5 Tutorial:** https://www.riverbankcomputing.com/static/Docs/PyQt5/
- **yfinance Docs:** https://pypi.org/project/yfinance/
- **pandas Docs:** https://pandas.pydata.org/docs/
- **Virtual Environments:** https://docs.python.org/3/tutorial/venv.html

---

**Powodzenia z instalacją!** 🚀

Jeśli wszystko działa, możesz uruchomić aplikację:
```bash
python portfolio_app.py
```
