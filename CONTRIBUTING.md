# Contributing to WALLET

Thank you for considering contributing to WALLET! 🎉

## 🌍 Language

- **English** is preferred for Issues and Pull Requests
- **Polish** is also welcome (developer is Polish)
- Code comments can be in either language

## 🤝 How to Contribute

### Reporting Bugs 🐛

1. Check if the bug is already reported in [Issues](https://github.com/kzaklikiewicz/wallet-app/issues)
2. If not, create a new issue with:
   - Clear title
   - Steps to reproduce
   - Expected vs actual behavior
   - Screenshots (if applicable)
   - Python version and OS
   - Log file (`Logs/Log_YYYY-MM-DD.txt`)

### Suggesting Features 💡

1. Check [Issues](https://github.com/kzaklikiewicz/wallet-app/issues) and [Discussions](https://github.com/kzaklikiewicz/wallet-app/discussions)
2. Open a new Discussion or Issue with:
   - Clear description of the feature
   - Use case / problem it solves
   - Possible implementation (optional)

### Code Contributions 👨‍💻

#### 1. Fork & Clone

```bash
# Fork the repository on GitHub, then:
git clone https://github.com/kzaklikiewicz/wallet-app.git
cd wallet-app
```

#### 2. Create a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/bug-description
```

#### 3. Set Up Development Environment

```bash
# Create virtual environment
python -m venv venv

# Activate it
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

#### 4. Make Changes

- Follow existing code style
- Add comments for complex logic
- Update documentation if needed
- Test your changes thoroughly

#### 5. Commit

```bash
git add .
git commit -m "feat: add amazing feature"
# or
git commit -m "fix: resolve issue with price updates"
```

**Commit message format:**
- `feat:` - new feature
- `fix:` - bug fix
- `docs:` - documentation changes
- `style:` - code style changes (formatting, etc.)
- `refactor:` - code refactoring
- `test:` - adding tests
- `chore:` - maintenance tasks

#### 6. Push & Create Pull Request

```bash
git push origin feature/your-feature-name
```

Then create a Pull Request on GitHub with:
- Clear description of changes
- Reference related issues (`Closes #123`)
- Screenshots (if UI changes)

## 📋 Code Style Guidelines

### Python Style
- Follow PEP 8 (mostly)
- Use meaningful variable names
- Keep functions focused and short
- Add docstrings to functions

```python
def calculate_profit(buy_price, current_price, quantity):
    """
    Calculate profit/loss for a position.
    
    Args:
        buy_price (float): Purchase price
        current_price (float): Current market price
        quantity (float): Number of shares
        
    Returns:
        float: Profit or loss amount
    """
    return (current_price - buy_price) * quantity
```

### UI/UX
- Keep UI consistent with existing design
- Use existing color scheme
- Test on different screen resolutions
- Ensure responsive layouts

### Database
- Never drop columns (add migrations instead)
- Use transactions for multiple operations
- Add indexes for frequently queried columns

## 🧪 Testing

Currently, the project doesn't have automated tests (yet!). When contributing:

1. **Manual testing is required**
2. Test on your local database
3. Test edge cases
4. Test with empty database
5. Test with large datasets (if performance-related)

### Test Checklist
- [ ] Application starts without errors
- [ ] New feature works as expected
- [ ] Existing features still work
- [ ] No errors in logs
- [ ] UI looks good
- [ ] Database migrations work

## 🔒 Security

If you discover a security vulnerability:

1. **DO NOT** open a public issue
2. Email the maintainer directly: [kamil.zaklikiewicz@gmail.com]
3. Include details, steps to reproduce, and potential impact

## 📝 Documentation

When adding features:
- Update README.md if user-facing
- Update code comments
- Add docstrings to new functions
- Update CHANGELOG.md

## 🎨 UI/Design Contributions

Design improvements are welcome! Please:
1. Discuss major UI changes in an Issue first
2. Maintain consistency with existing design
3. Consider accessibility (color contrast, font size)
4. Provide before/after screenshots

## 🌐 Translation

Currently supported languages: English, Polish

To add a new language:
1. Create translation files
2. Update UI to support language switching
3. Translate README

## ⚖️ License

By contributing, you agree that your contributions will be licensed under the MIT License.

## 🤔 Questions?

- Open a [Discussion](https://github.com/kzaklikiewicz/wallet-app/discussions)
- Check existing [Issues](https://github.com/kzaklikiewicz/wallet-app/issues)
- Email: [kamil.zaklikiewicz@gmail.com]

## 👥 Code of Conduct

Be respectful, constructive, and kind. We're all here to learn and improve the project together!

---

**Thank you for contributing! 🎉**
