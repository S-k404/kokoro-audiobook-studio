# Security Policy

## Supported versions

Only the latest release receives security fixes.

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's private
reporting instead: open the repository's **Security** tab and choose
**Report a vulnerability**. Include the version, steps to reproduce and the
impact. You can expect an initial response within a few days.

## Scope and design notes

- The local speech server has **no authentication** and listens on `127.0.0.1`
  by default. Exposing it to a network (`KOKORO_HOST=0.0.0.0`) is unsupported
  unless you put your own authentication or firewall in front of it.
- PDFs and EPUBs are parsed by third-party libraries (PyMuPDF, EbookLib). Only
  convert files you trust and keep dependencies up to date.
