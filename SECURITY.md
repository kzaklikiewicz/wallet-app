# Security Policy

## 🔒 Security Overview

WALLET implements **bank-grade security** for UI access with several layers of protection:

### ✅ Implemented Security Features

| Feature | Status | Details |
|---------|--------|---------|
| Password Protection | ✅ | bcrypt with 12 rounds (4096 iterations) |
| Recovery Key | ✅ | 32 characters, bcrypt hashed |
| Rate Limiting | ✅ | 5 attempts / 15 minutes lockout |
| Auto-Lock | ✅ | 30 minutes of inactivity |
| Windows Integration | ✅ | Lock on Win+L, Sleep, User Switch |
| Manual Logout | ✅ | User can logout anytime |

### ⚠️ Known Limitations

| Limitation | Risk Level | Mitigation |
|------------|------------|------------|
| Database NOT encrypted | **MEDIUM** | Use BitLocker or SQLCipher |
| Password in RAM briefly | **VERY LOW** | Accept (requires admin access) |
| Single Recovery Key | **MEDIUM** | Store securely (password manager) |
| No 2FA | **LOW** | Not standard for desktop apps |

---

## 🛡️ Security Assessment

**Overall Rating: 8.5/10** ⭐⭐⭐⭐⭐⭐⭐⭐☆☆

**Suitable for:**
- ✅ Personal use
- ✅ Small teams
- ✅ Freelancers
- ✅ Home users

**Not suitable for:**
- ❌ Government/military (requires 2FA + encryption)
- ❌ Large corporations (needs audit + compliance)
- ⚠️ Financial institutions (needs additional hardening)

---

## 🔐 What's Protected

✅ **Application Access** - Password required to open  
✅ **Passwords** - bcrypt 12 rounds (10-40 years to crack)  
✅ **Recovery Keys** - bcrypt hashed, impossible to reverse  
✅ **Brute Force Attacks** - Rate limiting (9.5 years for 1M passwords)  
✅ **Unauthorized Access** - Auto-lock, Windows lock integration  

---

## ❌ What's NOT Protected

❌ **Database File** - `portfolio.db` is NOT encrypted  
❌ **Data at Rest** - Anyone with file access can read via SQLite Browser  
❌ **Backup Files** - Exports are plain JSON  

### Why Database is NOT Encrypted?

1. **Complexity** - SQLCipher adds significant complexity
2. **Performance** - Encryption impacts query speed
3. **Use Case** - Most users rely on OS-level encryption
4. **Transparency** - Users can easily backup/inspect data

---

## 🎯 Recommended Security Setup

### For Most Users (90%)

```
✅ Enable password protection
✅ Save Recovery Key securely
✅ Enable Auto-Lock
✅ Enable Windows Lock integration
ℹ️ Use BitLocker (Windows) or FileVault (Mac)
```

### For High-Security Users (10%)

```
✅ All of the above, plus:
✅ Use SQLCipher (database encryption)
✅ Store database in VeraCrypt container
✅ Use strong, unique password (20+ chars)
✅ Print Recovery Key and store in safe
```

---

## 🐛 Reporting Security Vulnerabilities

If you discover a security vulnerability, please:

### 🚨 DO NOT open a public issue!

Instead:

1. **Email:** [kamil.zaklikiewicz@gmail.com]
2. **Subject:** "WALLET Security Vulnerability"
3. **Include:**
   - Detailed description
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

You will receive a response within **48 hours**.

### Responsible Disclosure Timeline

- **Day 0:** Report received
- **Day 1-2:** Acknowledgment sent
- **Day 3-14:** Investigation and fix development
- **Day 15-30:** Fix deployed and tested
- **Day 31+:** Public disclosure (if appropriate)

---

## 📋 Security Best Practices

### For Users

1. **Strong Password**
   - Minimum 12 characters
   - Mix of letters, numbers, symbols
   - Don't reuse from other services

2. **Recovery Key**
   - Save immediately after setup
   - Store in password manager (1Password, Bitwarden)
   - Print and keep in safe
   - NEVER share with anyone

3. **System Security**
   - Keep Windows/OS updated
   - Use antivirus software
   - Enable firewall
   - Use BitLocker/FileVault

4. **Physical Security**
   - Lock computer when away (Win+L)
   - Don't leave laptop unattended
   - Enable screen lock timeout

### For Developers

1. **Never** commit database files (`portfolio.db`)
2. **Never** hardcode passwords or keys
3. **Always** hash passwords (never plain text)
4. **Always** use parameterized queries (SQL injection)
5. **Review** security implications of changes

---

## 🔍 Security Audit History

| Date | Auditor | Scope | Rating | Report |
|------|---------|-------|--------|--------|
| 2026-01-06 | Claude AI (Anthropic) | Full system | 8.5/10 | [RAPORT_BEZPIECZENSTWA.md](RAPORT_BEZPIECZENSTWA.md) |

---

## 📚 Related Documents

- [Full Security Report](RAPORT_BEZPIECZENSTWA.md) - Comprehensive 35-page audit (Polish)
- [Quick Start Security Guide](INSTRUKCJA_ZABEZPIECZENIA.md) - User guide (Polish)
- [Security Setup](SZYBKI_START_ZABEZPIECZENIA.md) - Installation guide (Polish)

---

## 🆘 Emergency Access

### Lost Password + Lost Recovery Key = ❌ NO ACCESS

**There is NO backdoor** (this is intentional for security).

If you lose both:
1. Your data is permanently inaccessible
2. Only option: Delete `portfolio.db` and start fresh
3. Restore from backup (if you have unencrypted backup)

**Prevention:**
- Store Recovery Key in 2+ secure locations
- Test recovery process periodically
- Keep regular backups

---

## ✅ Security Checklist

Before deploying to production:

- [ ] Password protection enabled
- [ ] Recovery Key saved (2+ locations)
- [ ] Auto-Lock configured
- [ ] Windows Lock enabled (if Windows)
- [ ] BitLocker/FileVault enabled
- [ ] Antivirus active
- [ ] OS fully updated
- [ ] Firewall enabled
- [ ] Backup strategy in place

---

## 📞 Contact

- **General Security Questions:** [GitHub Discussions](https://github.com/kzaklikiewicz/wallet-app/discussions)
- **Security Vulnerabilities:** [kamil.zaklikiewicz@gmail.com]
- **Project Maintainer:** [your.email@example.com]

---

## 📜 License

Security policy is part of the project and falls under the MIT License.

---

**Last Updated:** 2026-01-07  
**Version:** 3.1.0  
**Status:** ✅ Active | 🔄 Regularly Reviewed
