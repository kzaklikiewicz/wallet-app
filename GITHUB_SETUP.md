# 🚀 Instrukcja Publikacji na GitHub - Krok po Kroku

## 📋 Przygotowane pliki

Masz już wszystkie potrzebne pliki:

### Główne pliki projektu
- ✅ `portfolio_app.py` - główna aplikacja
- ✅ `database.py` - warstwa bazy danych
- ✅ `auth_module.py` - system autoryzacji
- ✅ `budget_module.py` - moduł budżetu
- ✅ `media_module.py` - moduł mediów
- ✅ `requirements.txt` - zależności

### Pliki dokumentacji GitHub
- ✅ `README.md` - główny opis (angielski)
- ✅ `README_PL.md` - opis po polsku
- ✅ `LICENSE` - licencja MIT
- ✅ `.gitignore` - co ignorować w Git
- ✅ `CONTRIBUTING.md` - zasady współpracy
- ✅ `CHANGELOG.md` - historia zmian
- ✅ `SECURITY.md` - polityka bezpieczeństwa
- ✅ `RAPORT_BEZPIECZENSTWA.md` - pełny raport (Polski)

---

## 🎬 KROK 1: Przygotuj konto GitHub

### Jeśli nie masz konta:
1. Idź na https://github.com
2. Kliknij "Sign up"
3. Wybierz nazwę użytkownika (np. `jan-kowalski`)
4. Potwierdź email

### Jeśli masz konto:
1. Zaloguj się na https://github.com
2. Przejdź do swoich repozytoriów

---

## 🎬 KROK 2: Stwórz nowe repozytorium

1. Kliknij **"New"** (zielony przycisk) lub **"+"** → **"New repository"**

2. Wypełnij formularz:
   ```
   Repository name: wallet-app
   Description: 💵 Free desktop portfolio & budget management app
   Public/Private: ✅ Public (bo open source)
   Initialize: ❌ NIE zaznaczaj "Add a README file" (już masz)
   .gitignore: ❌ None (już masz)
   License: ❌ None (już masz LICENSE)
   ```

3. Kliknij **"Create repository"**

4. **ZAPISZ URL** który się pojawi (np. `https://github.com/jan-kowalski/wallet-app.git`)

---

## 🎬 KROK 3: Zainstaluj Git (jeśli nie masz)

### Windows:
1. Pobierz: https://git-scm.com/download/win
2. Zainstaluj z domyślnymi ustawieniami
3. Otwórz "Git Bash" z menu Start

### Linux:
```bash
sudo apt install git  # Ubuntu/Debian
sudo yum install git  # Fedora/CentOS
```

### macOS:
```bash
brew install git
# lub użyj Xcode Command Line Tools
```

### Sprawdź instalację:
```bash
git --version
# Powinno pokazać: git version 2.x.x
```

---

## 🎬 KROK 4: Skonfiguruj Git (tylko raz)

Otwórz terminal/Git Bash:

```bash
# Ustaw swoją nazwę
git config --global user.name "Jan Kowalski"

# Ustaw swój email (ten sam co w GitHub)
git config --global user.email "jan.kowalski@example.com"

# Sprawdź konfigurację
git config --list
```

---

## 🎬 KROK 5: Przygotuj folder projektu

### Struktura folderów:

```
C:\Twoj\Folder\wallet-app\
├── portfolio_app.py
├── database.py
├── auth_module.py
├── budget_module.py
├── media_module.py
├── requirements.txt
├── README.md
├── README_PL.md
├── LICENSE
├── .gitignore
├── CONTRIBUTING.md
├── CHANGELOG.md
├── SECURITY.md
├── RAPORT_BEZPIECZENSTWA.md
├── INSTRUKCJA_ZABEZPIECZENIA.md (opcjonalnie)
└── SZYBKI_START_ZABEZPIECZENIA.md (opcjonalnie)
```

### ⚠️ USUŃ przed publikacją:
```
❌ portfolio.db (Twoja baza danych - prywatne dane!)
❌ Logs/ (folder z logami)
❌ __pycache__/ (cache Pythona)
❌ venv/ lub env/ (virtual environment)
❌ .idea/ lub .vscode/ (IDE settings)
```

---

## 🎬 KROK 6: Zainicjuj repozytorium Git

Otwórz terminal/Git Bash w folderze projektu:

```bash
# Przejdź do folderu projektu
cd C:\Twoj\Folder\wallet-app

# Zainicjuj Git
git init

# Sprawdź status
git status
# Powinno pokazać listę plików "Untracked files"
```

---

## 🎬 KROK 7: Dodaj pliki do Git

```bash
# Dodaj wszystkie pliki (oprócz tych w .gitignore)
git add .

# Sprawdź co zostało dodane
git status
# Powinno pokazać "Changes to be committed" (zielone)

# ⚠️ UPEWNIJ SIĘ że NIE MA:
# - portfolio.db
# - Logs/
# - __pycache__/
```

---

## 🎬 KROK 8: Pierwszy commit

```bash
# Stwórz pierwszy commit
git commit -m "Initial commit - WALLET v3.1.0"

# Sprawdź historię
git log
# Powinien pokazać Twój commit
```

---

## 🎬 KROK 9: Połącz z GitHub

```bash
# Dodaj remote (użyj swojego URL z kroku 2!)
git remote add origin https://github.com/TWOJA-NAZWA/wallet-app.git

# Sprawdź remote
git remote -v
# Powinno pokazać origin (fetch) i origin (push)

# Ustaw nazwę głównej gałęzi
git branch -M main
```

---

## 🎬 KROK 10: Wypchnij kod na GitHub

```bash
# Wypchnij kod
git push -u origin main

# GitHub może poprosić o logowanie:
# - Podaj nazwę użytkownika GitHub
# - Zamiast hasła użyj Personal Access Token (patrz niżej)
```

### Jeśli GitHub prosi o hasło:

GitHub wymaga **Personal Access Token** zamiast hasła:

1. Idź na: https://github.com/settings/tokens
2. Kliknij **"Generate new token"** → **"Classic"**
3. Zaznacz: `repo` (pełny dostęp do repozytoriów)
4. Kliknij **"Generate token"**
5. **SKOPIUJ TOKEN** (zobaczysz go tylko raz!)
6. Użyj tego tokena jako "hasła" w Git

Alternatywnie - użyj **GitHub CLI** lub **GitHub Desktop** (łatwiejsze).

---

## 🎬 KROK 11: Sprawdź na GitHub

1. Odśwież stronę swojego repozytorium
2. Powinieneś zobaczyć wszystkie pliki!
3. README.md powinien się automatycznie wyświetlić

---

## 🎯 KROK 12: Ostatnie poprawki w plikach

### W README.md zamień:
```markdown
# BYŁO:
[GitHub Issues](https://github.com/kzaklikiewicz/wallet-app/issues)

# ZMIEŃ NA:
[GitHub Issues](https://github.com/TWOJA-NAZWA/wallet-app/issues)
```

### W LICENSE zamień:
```
Copyright (c) 2026 [Kamil Zaklikiewicz]
↓
Copyright (c) 2026 Twoje Imię Nazwisko
```

### Commituj zmiany:
```bash
git add README.md LICENSE
git commit -m "docs: update GitHub links and copyright"
git push
```

---

## 🎨 KROK 13: Dodaj zrzuty ekranu (opcjonalnie)

### Stwórz folder:
```bash
mkdir -p docs/screenshots
```

### Zrób zrzuty ekranu:
1. Otwórz aplikację
2. Zrób screenshoty (Win+Shift+S na Windows)
3. Zapisz jako:
   - `docs/screenshots/portfolio.png`
   - `docs/screenshots/budget.png`
   - `docs/screenshots/login.png`

### Dodaj do Git:
```bash
git add docs/
git commit -m "docs: add screenshots"
git push
```

---

## 🏷️ KROK 14: Stwórz Release (wersja)

1. Na GitHub → Twoje repo → **"Releases"** → **"Create a new release"**
2. Wypełnij:
   ```
   Tag version: v3.1.0
   Release title: WALLET v3.1.0 - Password Protection & Windows Lock
   Description: (skopiuj z CHANGELOG.md)
   ```
3. Opcjonalnie: Dodaj skompilowany `.exe` jako Asset
4. Kliknij **"Publish release"**

---

## 📢 KROK 15: Promuj projekt

### Dodaj Topics (tagi):
1. Na stronie repo → **⚙️** (koło "About") → **"Topics"**
2. Dodaj:
   ```
   python, pyqt5, portfolio, budget, finance, desktop-app,
   investment, open-source, sqlite, stock-market
   ```

### Dodaj opis:
1. **⚙️** (koło "About") → **Description**
2. Wpisz: `💵 Free desktop portfolio & budget management app (Python + PyQt5)`
3. Zaznacz: ✅ **"Include in the home page"**

---

## 🎉 GOTOWE! Twój projekt jest live!

URL: `https://github.com/TWOJA-NAZWA/wallet-app`

---

## 📝 Przyszłe aktualizacje

Gdy wprowadzisz zmiany:

```bash
# 1. Dodaj zmienione pliki
git add .

# 2. Commit
git commit -m "feat: add new awesome feature"

# 3. Push
git push

# Gotowe! Zmiany są na GitHub
```

---

## ⚠️ Częste problemy

### Problem: `permission denied`
**Rozwiązanie:** Użyj Personal Access Token zamiast hasła

### Problem: `rejected - non-fast-forward`
```bash
git pull --rebase
git push
```

### Problem: `repository not found`
**Rozwiązanie:** Sprawdź czy URL remote jest poprawny:
```bash
git remote -v
# Jeśli błędny:
git remote set-url origin https://github.com/TWOJA-NAZWA/wallet-app.git
```

### Problem: `.gitignore` nie działa
```bash
# Usuń cache i dodaj ponownie
git rm -r --cached .
git add .
git commit -m "fix: apply .gitignore"
git push
```

---

## 🆘 Pomoc

- **GitHub Docs:** https://docs.github.com
- **Git Tutorial:** https://git-scm.com/book/en/v2
- **Problemy:** Otwórz Issue w swoim repo

---

## ✅ Checklist końcowy

Przed publikacją upewnij się że:

- [ ] `portfolio.db` NIE jest w repozytorium
- [ ] Folder `Logs/` NIE jest w repozytorium
- [ ] Zaktualizowałeś linki w README (kzaklikiewicz → twoja nazwa)
- [ ] Zaktualizowałeś LICENSE (Kamil Zaklikiewicz → twoje imię)
- [ ] Zaktualizowałeś email w CONTRIBUTING.md
- [ ] Zaktualizowałeś email w SECURITY.md
- [ ] Dodałeś zrzuty ekranu (opcjonalnie)
- [ ] Dodałeś Topics na GitHub
- [ ] Stworzyłeś Release v3.1.0

---

**Gratulacje! Jesteś teraz open-source developerem! 🎉**

Możesz teraz udostępnić link na grupie finansowej! 🚀
