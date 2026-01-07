# 💵 WALLET - Portfolio & Budget Management App

![Python](https://img.shields.io/badge/python-3.8+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)

**WALLET** is a free, open-source desktop application for managing investment portfolios, household budgets, and utility tracking. Built with Python and PyQt5, it works completely offline with your data stored locally.

[🇵🇱 Polish Version](README_PL.md) | [📸 Screenshots](#screenshots) | [🚀 Quick Start](#quick-start)

---

## 🌟 Features

### 📊 Portfolio Management
- Multi-currency support (USD/PLN with automatic exchange rates)
- Real-time price updates from Yahoo Finance
- Automatic P&L calculation
- Transaction history tracking
- Watchlist with 4-level price alerts (HP1-HP4)
- Investment strategies system
- Export/Import functionality

### 💰 Budget Module
- Income tracking
- Expense categorization
- Recurring expenses management
- Monthly summaries and charts

### 📊 Utilities Tracking
- Water, electricity, gas consumption monitoring
- Historical data and trends
- Cost calculations

### 🔒 Security
- Password protection (bcrypt encryption)
- Rate limiting (5 attempts / 15 minutes)
- Auto-lock after inactivity
- Windows session lock integration (Win+L)
- Recovery key system
- Manual logout option

---

## 📸 Screenshots

### Portfolio View
![Portfolio](docs/screenshots/portfolio.png)

### Budget Module
![Budget](docs/screenshots/budget.png)

### Security Login
![Login](docs/screenshots/login.png)

---

## 🎯 Why This App?

This application was created to solve several problems:

✅ **No Excel limitations** - Full automation, API integration, professional UI  
✅ **No cloud dependency** - All data stored locally, works offline  
✅ **Portable** - Run from USB drive, no installation needed  
✅ **Open source** - Full control, modify as you need  
✅ **AI-assisted development** - Built with Claude AI (Anthropic) as a proof of concept  

---

## 🚀 Quick Start

### kzaklikiewicz
- Python 3.8 or higher
- Windows 10/11, Linux, or macOS

### Installation

```bash
# Clone repository
git clone https://github.com/YOUR_USERNAME/wallet-app.git
cd wallet-app

# Install dependencies
pip install -r requirements.txt

# Run application
python portfolio_app.py
```

### First Run
1. Application creates `portfolio.db` automatically
2. Optionally set up password protection in Settings
3. Start adding positions or using budget module

---

## 📦 Requirements

```
PyQt5>=5.15.0
yfinance>=0.2.0
pandas>=1.5.0
requests>=2.28.0
bcrypt>=4.0.0
pywin32>=305 (Windows only)
```

---

## 🔧 Configuration

### Enable Password Protection
1. Go to **Settings** → **Security**
2. Click **Set Password**
3. Save your **Recovery Key** (XXXX-XXXX-XXXX-XXXX)
4. Optional: Enable **Auto-Lock** and **Windows Lock Integration**

### Database Location
By default, `portfolio.db` is created in the application directory. You can move it to any location (USB drive, encrypted folder, etc.).

---

## 🏗️ Architecture

```
wallet-app/
├── portfolio_app.py      # Main application
├── database.py           # Database layer (SQLite)
├── auth_module.py        # Authentication system
├── budget_module.py      # Budget functionality
├── media_module.py       # Utilities tracking
├── requirements.txt      # Dependencies
├── portfolio.db          # SQLite database (created on first run)
└── Logs/                 # Application logs
```

---

## 🔒 Security

### What's Protected
✅ UI access (password required)  
✅ Passwords (bcrypt with 12 rounds)  
✅ Recovery keys (bcrypt hashed)  
✅ Rate limiting (brute-force protection)  
✅ Auto-lock on inactivity  
✅ Windows session integration  

### What's NOT Protected
❌ Database file (`portfolio.db`) is **NOT encrypted**  
❌ Anyone with file access can read data using SQLite Browser  

### Recommendations
- Use **BitLocker** (Windows) or **FileVault** (macOS) for full disk encryption
- Consider using **SQLCipher** for database encryption (advanced)
- Store Recovery Key securely (password manager, safe, etc.)

**Full Security Report:** [SECURITY.md](SECURITY.md)

---

## 🎨 Customization

The application is designed to be easily modified:

### Change Colors
Edit CSS styles in `portfolio_app.py`:
```python
self.settings_btn.setStyleSheet("""
    QPushButton {
        background-color: #6b7280;  # Change this
        color: white;
    }
""")
```

### Add New Features
1. Modify database schema in `database.py`
2. Add UI components in `portfolio_app.py`
3. Connect signals to slots

### Create Your Own Module
Follow the structure of `budget_module.py` or `media_module.py`

---

## 📊 Performance

- **Startup time:** < 2 seconds
- **Portfolio loading:** Instant (hybrid cache system)
- **Price refresh:** 100+ tickers in < 10 seconds (batch download)
- **Database size:** ~2-5 MB for typical usage
- **Memory usage:** ~150-200 MB

---

## 🐛 Troubleshooting

### "No module named 'PyQt5'"
```bash
pip install PyQt5
```

### "No module named 'win32api'" (Windows)
```bash
pip install pywin32
```

### Database locked error
Close all instances of the application and try again.

### Prices not updating
Check internet connection and firewall settings (Yahoo Finance API access required).

---

## 🤝 Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### How to Contribute
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Development Setup
```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/wallet-app.git

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run in development mode
python portfolio_app.py
```

---

## 📝 License

This project is licensed under the **MIT License** - see [LICENSE](LICENSE) file for details.

**TL;DR:** You can use, modify, distribute, and even sell this software. No restrictions, no warranty.

---

## 🙏 Acknowledgments

- **Claude AI (Anthropic)** - AI assistant that helped build this application
- **yfinance** - Yahoo Finance API wrapper
- **PyQt5** - GUI framework
- **Community** - All contributors and users

---

## 📞 Contact & Support

- **Issues:** [GitHub Issues](https://github.com/YOUR_USERNAME/wallet-app/issues)
- **Discussions:** [GitHub Discussions](https://github.com/YOUR_USERNAME/wallet-app/discussions)
- **Email:** your.email@example.com

---

## 🗺️ Roadmap

### Version 3.2 (Planned)
- [ ] Database encryption (SQLCipher)
- [ ] Export to Excel
- [ ] More chart types
- [ ] Mobile companion app

### Version 4.0 (Future)
- [ ] Multi-user support
- [ ] Cloud sync (optional)
- [ ] Advanced analytics
- [ ] Portfolio optimization tools

---

## ⭐ Star History

If you find this project useful, please consider giving it a star! ⭐

---

## 📜 Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history.

---

## 🎓 Learning Resources

This project was built as a demonstration of:
- AI-assisted software development
- PyQt5 desktop application architecture
- SQLite database design
- Financial data API integration
- Security best practices

Feel free to use it as a learning resource!

---

**Made with ❤️ and AI assistance (Claude by Anthropic)**

**Status:** ✅ Production Ready | 🔄 Actively Maintained | 📖 Well Documented
